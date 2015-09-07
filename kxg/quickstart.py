#!/usr/bin/env python3

import linersock
import multiprocessing, queue
import logging, logging.handlers
from .errors import *
from .theater import *

default_host = 'localhost'
default_port = 53351

class ClientConnectionStage (Stage):

    def __init__(self, world, gui_actor, host, port):
        super().__init__()
        self.world = world
        self.gui_actor = gui_actor
        self.host = host
        self.port = port
        self.pipe = None
        self.client = linersock.Client(
                host, port, callback=self.on_connection_established)

    def on_update_stage(self, time):
        self.client.connect()
        try: self.gui.on_refresh_gui()
        except: pass

    def on_connection_established(self, pipe):
        self.pipe = pipe
        self.exit_stage()

    def on_exit_stage(self):
        game_stage = MultiplayerClientGameStage(
                self.world, self.gui_actor, self.pipe)
        game_stage.successor.successor = PostgameSplashStage()
        self.successor = game_stage


class ServerConnectionStage (Stage):

    def __init__(self, world, referee, num_clients, ai_actors=[], host=default_host, port=default_port):
        super().__init__()
        self.world = world
        self.referee = referee
        self.ai_actors = ai_actors
        self.host = host
        self.port = port
        self.pipes = []
        self.greetings = []
        self.server = linersock.Server(
                host, port, num_clients, self.on_clients_connected)

    def on_enter_stage(self):
        self.server.open()

    def on_update_stage(self, dt):
        if not self.server.finished():
            self.server.accept()
        else:
            self.exit_stage()

    def on_clients_connected(self, pipes):
        self.pipes += pipes

    def on_exit_stage(self):
        self.successor = MultiplayerServerGameStage(
                self.world, self.referee, self.ai_actors, self.pipes)


class PostgameSplashStage (Stage):
    """
    Until the player closes the window, keep it as it was when the game ended.
    """

    def on_update_stage(self, dt):
        try: self.gui.on_refresh_gui()
        except: self.exit_stage()


class ProcessPool:
    """
    Manage a group of processes running instances of the game loop.

    This class wraps around the basic multiprocessing functionality available 
    in the python standard library.  There are two nice features provided by 
    this class.  The first is that log messages generated in the subprocesses 
    are automatically relayed to the main process, where they are reported 
    with the name of the original process included and without any mangling due 
    to race conditions.  The second is that exceptions, which are usually 
    silently ignored in subprocesses, are also relayed to the main process and 
    re-raised.

    This class is actually not specific to the game engine at all, so in 
    principle it could be moved into it's own library.  I decided not to do 
    that because I can't think of any other scenario where I would want the 
    functionality that this class offers, but maybe I'll think of one later.
    """

    def __init__(self, time_limit=None, frame_rate=30):
        self.log_queue = multiprocessing.Queue()
        self.exception_queue = multiprocessing.Queue()
        self.time_limit = time_limit
        self.elapsed_time = 0
        self.frame_rate = frame_rate

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._run_supervisor()


    def start(self, name, worker, *args, **kwargs):
        process = multiprocessing.Process(
                name=name, target=self._run_worker,
                args=(name, worker) + args, kwargs=kwargs,
        )
        process.start()

    def _run_worker(self, name, worker, *args, **kwargs):

        # Configure all logging message generated by this process to go into a 
        # queue that will be read and handled by the supervisor.

        handler = logging.handlers.QueueHandler(self.log_queue)
        logging.root.addHandler(handler)

        # Catch any exceptions generated by the worker and report them to the 
        # supervisor.  This is important, because otherwise they would be 
        # silently ignored.

        try:
            worker(*args, **kwargs)
        except Exception as exception:
            self.exception_queue.put_nowait(exception)

    def _run_supervisor(self):
        """
        Poll the queues that the worker can use to communicate with the 
        supervisor, until all the workers are done and all the queues are 
        empty.  Handle messages as they appear.
        """
        import time

        still_supervising = lambda: (
                multiprocessing.active_children()
                or not self.log_queue.empty()
                or not self.exception_queue.empty())

        try:
            while still_supervising():
                # When a log message is received, make a logger in this process 
                # with the same name and use it to re-log the message.  It will 
                # get handled in this process.

                try:
                    record = self.log_queue.get_nowait()
                    logger = logging.getLogger(record.name)
                    logger.handle(record)
                except queue.Empty:
                    pass

                # When an exception is received, immediately re-raise it.

                try:
                    exception = self.exception_queue.get_nowait()
                except queue.Empty:
                    pass
                else:
                    raise exception

                # Sleep for a little bit, and make sure that the workers haven't 
                # outlived their time limit.

                time.sleep(1/self.frame_rate)
                self.elapsed_time += 1/self.frame_rate

                if self.time_limit and self.elapsed_time > self.time_limit:
                    raise RuntimeError("timeout")

        # Make sure the workers don't outlive the supervisor, no matter how the 
        # polling loop ended (e.g. normal execution or an exception).

        finally:
            for process in multiprocessing.active_children():
                process.terminate()



class MultiplayerDebugger:
    """
    Simultaneously plays any number of different game theaters, executing each 
    theater in its own process.  This greatly facilitates the debugging and 
    testing multiplayer games.
    """

    def __init__(self, world_cls, referee_cls, gui_cls, gui_actor_cls,
            num_guis=2, ai_actor_cls=None, num_ais=0, theater_cls=PygletTheater,
            host=default_host, port=default_port, log_format=
            '%(levelname)s: %(processName)s: %(name)s: %(message)s'):

        # Members of this class have to be pickle-able, because this object 
        # will be pickled and sent to every process that gets started.  That's 
        # why all the game objects are stored as classes (or factories) rather 
        # than instances.  Even though some of the game objects can be pickled, 
        # none of them are meant to be and avoiding it reduces the risk that 
        # things will break for strange reasons.  The game objects themselves 
        # are instantiated in the worker processes, which is how it would 
        # happen if the user just rame multiple instances of the game anyway.

        self.theater_cls = theater_cls
        self.world_cls = world_cls
        self.referee_cls = referee_cls
        self.gui_cls = gui_cls
        self.gui_actor_cls = gui_actor_cls
        self.num_guis = num_guis
        self.ai_actor_cls = ai_actor_cls
        self.num_ais = num_ais
        self.host = host
        self.port = port
        self.log_format = log_format

    def play(self, executor=None):
        # Configure the logging system to print to stderr and include the 
        # process name in all of its messages.

        handler = logging.StreamHandler()
        formatter = logging.Formatter(self.log_format)
        handler.setFormatter(formatter)
        logging.root.addHandler(handler)

        # Run the server and the client (each in its own process).

        with ProcessPool() as pool:
            pool.start("Server", self.play_server)
            for i in range(self.num_guis):
                pool.start("Client #%d" % i, self.play_client)

    def play_server(self):
        # Defer instantiation of all the game objects until we're inside our 
        # own process, to avoid having to pickle and unpickle things that 
        # should be pickled.

        theater = self.theater_cls()
        theater.initial_stage = ServerConnectionStage(
                world=self.world_cls(),
                referee=self.referee_cls(),
                num_clients=self.num_guis,
                ai_actors=[ai_actor_cls() for i in range(self.num_ais)],
                host=self.host,
                port=self.port,
        )
        theater.play()

    def play_client(self):
        # Defer instantiation of all the game objects until we're inside our 
        # own process, to avoid having to pickle and unpickle things that 
        # should be pickled.

        theater = self.theater_cls()
        theater.gui = self.gui_cls()
        theater.initial_stage = ClientConnectionStage(
                world=self.world_cls(),
                gui_actor=self.gui_actor_cls(),
                host=self.host,
                port=self.port,
        )
        theater.play()



def main(world_cls, referee_cls, gui_cls, gui_actor_cls, ai_actor_cls,
        theater_cls=PygletTheater, default_host=default_host,
        default_port=default_port, argv=None):
    """
Run a game being developed with the kxg game engine.

Usage:
    {sys.argv[0]} sandbox [<num_ais>] [-v...]
    {sys.argv[0]} client [--host HOST] [--port PORT] [-v...]
    {sys.argv[0]} server <num_guis> [<num_ais>] [options] [-v...] 
    {sys.argv[0]} debug <num_guis> [<num_ais>] [options] [-v...]
    {sys.argv[0]} --help

Commands:
    sandbox
        Play a single-player game with the specified number of AIs.  None of 
        the multiplayer machinery will be used.

    client
        Launch a client that will try to connect to a server on the given host 
        and port.  Once it connects and the game starts, the client will allow 
        you to play the game against any other connected clients.

    server
        Launch a server that will manage a game between the given number of 
        human and AI players.  The human players must connect using this 
        command's client mode.

    debug
        Debug a multiplayer game locally.  This command launches a server and 
        the given number of clients all in different processes, and configures 
        the logging system such that the output from each process can be easily 
        distinguished.

Arguments:
    <num_guis>
        The number of human players that will be playing the game.  Only needed 
        by commands that will launch some sort of multiplayer server.

    <num_ais>
        The number of AI players that will be playing the game.  Only needed by 
        commands that will launch single-player games or multiplayer servers.

Options:
    -x --host HOST          [default: {default_host}]
        The address of the machine running the server.  Must be accessible from 
        the machines running the clients.

    -p --port PORT          [default: {default_port}]
        The port that the server should listen on.  Don't specify a value less 
        than 1024 unless the server is running with root permissions.

    -v --verbose 
        Have the game engine log more information about what it's doing.  You 
        can specify this option several times to get more and more information.

This command is provided so that you can start writing your game with the least 
possible amount of boilerplate code.  However, the clients and servers provided 
by this command are not capable of running a production game.  Once you have 
written your game and want to give it a polished set of menus and options, 
you'll have to write new Stage subclasses encapsulating that logic and you'll 
have to call those stages yourself by interacting more directly with the 
Theater class.  The online documentation has more information on this process.
    """
    import sys, docopt, logging, nonstdlib

    usage = main.__doc__.format(**locals()).strip()
    args = docopt.docopt(usage, argv or sys.argv[1:])
    num_guis = int(args['<num_guis>'] or 1)
    num_ais = int(args['<num_ais>'] or 0)
    host, port = args['--host'], int(args['--port'])

    logging.basicConfig(
            format='%(levelname)s: %(name)s: %(message)s',
            level=nonstdlib.verbosity(args['--verbose']),
    )

    # Use the given game objects and command line arguments to play a game!

    if args['debug']:
        print("""\
****************************** KNOWN BUG WARNING ******************************
In debug mode, every message produced by the logging system gets printed twice.
I know vaguely why this is happening, but as of yet I've not been able to fix
it.  In the mean time, don't let this confuse you!
*******************************************************************************""")
        game = MultiplayerDebugger(
                world_cls, referee_cls, gui_cls, gui_actor_cls, num_guis,
                ai_actor_cls, num_ais, theater_cls, host, port)
    else:
        game = theater_cls()
        ai_actors = [ai_actor_cls() for i in range(num_ais)]

        if args['sandbox']:
            game.gui = gui_cls()
            game.initial_stage = UniplayerGameStage(
                    world_cls(), referee_cls(), gui_actor_cls(), ai_actors)
            game.initial_stage.successor = PostgameSplashStage()

        if args['client']:
            game.gui = gui_cls()
            game.initial_stage = ClientConnectionStage(
                    world_cls(), gui_actor_cls(), host, port)

        if args['server']:
            game.initial_stage = ServerConnectionStage(
                    world_cls(), referee_cls(), num_guis, ai_actors,
                    host, port)

    game.play()

