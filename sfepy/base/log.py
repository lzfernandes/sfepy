from base import *
from sfepy.base.tasks import Process, Pipe

try:
    import gobject
except ImportError:
    pass

try:
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    from matplotlib.ticker import LogLocator, AutoLocator
except:
    plt = None

if (mpl is not None) and mpl.rcParams['backend'] == 'GTKAgg':
    can_live_plot = True
else:
    can_live_plot = False

_msg_no_live = """warning: log plot is disabled, install matplotlib
         (use GTKAgg backend) and multiprocessing"""

    
class ProcessPlotter( Struct ):
    output = Output('plotter:',
                    filename=os.path.join(sfepy_config_dir,'plotter.log'))
    output = staticmethod( output )

    def __init__( self, aggregate = 100 ):
        Struct.__init__( self, aggregate = aggregate )

    def process_command( self, command ):
        self.output( command[0] )

        if command[0] == 'ig':
            self.ig = command[1]

        elif command[0] == 'plot':
            ig = self.ig
            ax = self.ax[ig]
            ax.set_yscale(self.yscales[ig])
            ax.yaxis.grid(True)
            ax.plot(command[1], command[2])

            if self.yscales[ig] == 'log':
                ymajor_formatter = ax.yaxis.get_major_formatter()
                ymajor_formatter.label_minor(True)
                yminor_locator = LogLocator()
            else:
                yminor_locator = AutoLocator()
                self.ax[ig].yaxis.set_minor_locator(yminor_locator)

        elif command[0] == 'clear':
            for ax in self.ax:
                ax.cla()

        elif command[0] == 'legends':
            for ig, ax in enumerate(self.ax):
                ax.legend(self.data_names[ig])
                if self.xlabels[ig]:
                    ax.set_xlabel(self.xlabels[ig])
                if self.ylabels[ig]:
                    ax.set_ylabel(self.ylabels[ig])

        elif command[0] == 'add_axis':
            ig, names, yscale, xlabel, ylabel = command[1:]
            self.data_names[ig] = names
            self.yscales[ig] = yscale
            self.xlabels[ig] = xlabel
            self.ylabels[ig] = ylabel
            self.n_gr = len(self.data_names)
            self.make_axes()

        elif command[0] == 'save':
            self.fig.savefig(command[1])


    def terminate( self ):
        if self.ii:
            self.output( 'processed %d commands' % self.ii )
        self.output( 'ended.' )
        plt.close( 'all' )

    def poll_draw( self ):

        def call_back():
            self.ii = 0
            
            while 1:
                if not self.pipe.poll():
                    break

                command = self.pipe.recv()
                can_break = False

                if command is None:
                    self.terminate()
                    return False
                elif command[0] == 'continue':
                    can_break = True
                else:
                    self.process_command( command )

                if (self.ii >= self.aggregate) and can_break:
                    break

                self.ii += 1

            if self.ii:
                self.fig.canvas.draw()
                self.output( 'processed %d commands' % self.ii )

            return True

        return call_back

    def make_axes(self):
        self.fig.clf()
        self.ax = []
        for ig in range( self.n_gr ):
            isub = 100 * self.n_gr + 11 + ig
            self.ax.append( self.fig.add_subplot( isub ) )
    
    def __call__(self, pipe, data_names, yscales, xlabels, ylabels):
        """Sets-up the plotting window, sets GTK event loop timer callback to
        callback() returned by self.poll_draw(). The callback does the actual
        plotting, taking commands out of `pipe`, and is called every second."""
        self.output( 'starting plotter...' )
#        atexit.register( self.terminate )

        self.pipe = pipe
        self.data_names = data_names
        self.yscales = yscales
        self.xlabels = xlabels
        self.ylabels = ylabels
        self.n_gr = len(data_names)

        self.fig = plt.figure()
        self.make_axes()
        self.gid = gobject.timeout_add( 1000, self.poll_draw() )

        self.output( '...done' )
        plt.show()

def name_to_key( name, ii ):
    return name + (':%d' % ii)

class Log( Struct ):
    """Log data and (optionally) plot them in the second process via
    ProcessPlotter."""

    def from_conf( conf, data_names ):
        """`data_names` ... tuple of names grouped by subplots:
                            ([name1, name2, ...], [name3, name4, ...], ...)
        where name<n> are strings to display in (sub)plot legends."""
        if not isinstance( data_names, tuple ):
            data_names = (data_names,)

        obj = Log(data_names, **conf)

        return obj
    from_conf = staticmethod( from_conf )

    def __init__(self, data_names, is_plot=True, aggregate=200, yscales=None,
                 xlabels=None, ylabels=None):
        """`data_names` ... tuple of names grouped by subplots:
                            ([name1, name2, ...], [name3, name4, ...], ...)
        where name<n> are strings to display in (sub)plot legends."""
        Struct.__init__(self, data_names = {},
                        n_arg = 0, n_gr = 0,
                        data = {}, x_values = {}, n_calls = 0,
                        yscales = {}, xlabels = {}, ylabels = {},
                        plot_pipe = None)

        n_gr = len(data_names)
        yscales = get_default(yscales, ['linear'] * n_gr)
        xlabels = get_default(xlabels, ['iteration'] * n_gr)
        ylabels = get_default(ylabels, [''] * n_gr )

        for ig, names in enumerate(data_names):
            self.add_group(names, yscales[ig], xlabels[ig], ylabels[ig])

        self.is_plot = get_default( is_plot, True )
        self.aggregate = get_default( aggregate, 100 )

        self.can_plot = (can_live_plot and (plt is not None)
                         and (Process is not None))

        if self.is_plot and (not self.can_plot):
            output(_msg_no_live)
    
    def add_group(self, names, yscale=None, xlabel=None, ylabel=None):
        """Add a new data group. Notify the plotting process if it is
        already running."""
        ig = self.n_gr
        self.n_gr += 1

        self.x_values[ig] = []

        self.data_names[ig] = names
        self.yscales[ig] = yscale
        self.xlabels[ig] = xlabel
        self.ylabels[ig] = ylabel
        
        ii = self.n_arg
        for name in names:
            key = name_to_key(name, ii)
            self.data[key] = []
            ii += 1

        self.n_arg = ii

        if self.plot_pipe is not None:
            send = self.plot_pipe.send
            send(['add_axis', ig, names, yscale, xlabel, ylabel])

    def iter_names(self):
        ii = 0
        for ig, names in ordered_iteritems(self.data_names):
            for name in names:
                yield ig, ii, name
                ii += 1

    def __call__( self, *args, **kwargs ):
        """Log the data passed via *args, and send them to the plotting
        process, if available."""
        finished = False
        save_figure = ''
        x_values = None
        if kwargs:
            if 'finished' in kwargs:
                finished = kwargs['finished']
            if 'save_figure' in kwargs:
                save_figure = kwargs['save_figure']
            if 'x' in kwargs:
                x_values = kwargs['x']

        if save_figure and (self.plot_pipe is not None):
            self.plot_pipe.send( ['save', save_figure] )

        if finished:
            self.terminate()
            return

        ls = len( args ), self.n_arg
        if ls[0] != ls[1]:
            if kwargs:
                return
            else:
                msg = 'log called with wrong number of arguments! (%d == %d)' \
                      % ls
                raise IndexError( msg )

        for ig, ii, name in self.iter_names():
            aux = args[ii]
            if isinstance( aux, nm.ndarray ):
                aux = nm.array( aux, ndmin = 1 )
                if len( aux ) == 1:
                    aux = aux[0]
                else:
                    raise ValueError, 'can log only scalars (%s)' % aux
            key = name_to_key( name, ii )
            self.data[key].append( aux )

        for ig in range( self.n_gr ):
            if (x_values is not None) and x_values[ig]:
                self.x_values[ig].append( x_values[ig] )
            else:
                self.x_values[ig].append( self.n_calls )

        if self.is_plot and self.can_plot:
            if self.n_calls == 0:
                atexit.register( self.terminate )

                self.plot_pipe, plotter_pipe = Pipe()
                self.plotter = ProcessPlotter( self.aggregate )
                self.plot_process = Process( target = self.plotter,
                                             args = (plotter_pipe,
                                                     self.data_names,
                                                     self.yscales,
                                                     self.xlabels,
                                                     self.ylabels) )
                self.plot_process.daemon = True
                self.plot_process.start()

            self.plot_data()
            
        self.n_calls += 1

    def terminate( self ):
        if self.is_plot and self.can_plot:
            self.plot_pipe.send( None )
            self.plot_process.join()
            self.n_calls = 0
            output( 'terminated' )

    def plot_data( self ):
        send = self.plot_pipe.send

        send(['clear'])
        for ig, ii, name in self.iter_names():
            key = name_to_key(name, ii)
            try:
                send(['ig', ig])
                send(['plot',
                      nm.array(self.x_values[ig]),
                      nm.array(self.data[key])])
            except:
                msg = "send failed! (%s, %s, %s)!" % (ii, name, self.data[key])
                raise IOError(msg)
        send(['legends'])
        send(['continue'])
