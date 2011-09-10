#!/usr/bin/env python

import random

from helpers.pipes import *
from helpers.interface import *

# I completely forgot to test the forgetting methods.

# Setup {{{1
def setup(integrate=lambda x: x):
    tests = {}, {}
    direction = True, False

    for test, reverse in zip(tests, direction):
        sender, receiver = connect(reverse=reverse, integrate=integrate)
        inbox, outbox = Inbox(), Outbox()

        test["sender"], test["receiver"] = sender, receiver
        test["inbox"], test["outbox"] = inbox, outbox

        flavor = outbox.flavor()

        sender.outgoing(flavor, outbox.send)
        receiver.incoming(flavor, inbox.receive)

    return tests

# Send {{{1
def send(test, bytes=8):
    sender, outbox = test["sender"], test["outbox"]

    message = outbox.message(bytes)
    sender.queue(message)

# Receive {{{1
def receive(test):
    sender, receiver = test["sender"], test["receiver"]
    inbox, outbox = test["inbox"], test["outbox"]

    update(sender, receiver)
    disconnect(sender, receiver)

    inbox.check(outbox)

# }}}1

# Simple Tests {{{1
def test_one_message():
    for test in setup():
        send(test)
        receive(test)

def test_two_messages():
    for test in setup():
        send(test); send(test)
        receive(test)

def test_message_tags():

    client, server = connect()
    inbox, outbox = Inbox(), Outbox()

    flavor = Outbox.flavor()
    message = Outbox.message()

    def expect(origin, ticker):

        def function(pipe, tag, message):
            assert tag == origin, ticker

        return function

    client.incoming(flavor, expect(1, 1))
    server.incoming(flavor, expect(2, 1))

    
    

    # These values should be assigned by the server within connect.
    assert server.get_identity() == 1
    assert client.get_identity() == 2

def test_multiple_clients():
    clients, servers = connect(10)
    inbox, outbox = Inbox(), Outbox()

    flavor = outbox.flavor()
    message = outbox.message()

    for client in clients:
        client.outgoing(flavor, outbox.send)

    for server in servers:
        server.incoming(flavor, inbox.receive)

    inbox.check(outbox)

def test_defaults():
    sender, receiver = connect()
    inbox, outbox = Inbox(), Outbox()

    message = outbox.message()

    sender.outgoing_default(outbox.send)
    receiver.incoming_default(inbox.receive)

    sender.queue(message)

    update(sender, receiver)
    disconnect(sender, receiver)

    inbox.check(outbox)

def test_surprises():
    sender, receiver = connect()
    inbox, outbox = Inbox(), Outbox()

    flavor = outbox.flavor()
    message = outbox.message()

    sender.queue(message)

    # By default, outgoing messages must be registered.
    try: update(sender)
    except AssertionError: pass
    else: raise AssertionError

    sender.outgoing(flavor)
    sender.queue(message)

    # Incoming messages also have to be registered.
    try: update(sender, receiver)
    except AssertionError: pass
    else: raise AssertionError

    receiver.incoming(flavor, lambda *ignore: None)
    sender.queue(message)

    update(sender, receiver)
    disconnect(sender, receiver)

def test_integration():

    def integrate(message):
        message.integrated = True
        return message

    for test in setup(integrate):
        send(test)
        receive(test)

        for message in test["inbox"]:
            assert hasattr(message, "integrated")

# Rigorous Tests {{{1
def test_stressful_conditions(count, bytes):
    for test in setup():
        for iteration in range(count):
            send(test, bytes)
        receive(test)

def test_many_messages():
    test_stressful_conditions(count=2**12, bytes=2**4)

def test_large_messages():
    test_stressful_conditions(count=2**4, bytes=2**17)

def test_partial_messages(count=2**8, bytes=2**8):
    client, server = connect()
    inbox, outbox = Inbox(), Outbox()

    flavor = outbox.flavor()
    messages = [ outbox.message(bytes) for index in range(count) ]

    buffers = range(2 * bytes)

    client.outgoing(flavor, outbox.send)
    server.incoming(flavor, inbox.receive)

    # Place the messages onto the delivery queue to create a stream.
    for message in messages:
        client.queue(message)

    socket = client.socket
    stream = client.stream_out

    # Manually deliver the stream in small chunks.
    while stream:
        size = random.choice(buffers)
        head, stream = stream[:size], stream[size:]

        socket.send(head)
        server.receive()
    
    disconnect(client, server)

    # Make sure all the messages were properly received.
    inbox.check(outbox)

# }}}1

# New Tests

# Test Ideas
# ==========
# 1. Test isolated hosts/clients/servers.
#     a. Host.open()
#     b. Host.accept() -- Null case
#     c. Host.close()
#     d. Host.finished()
#     e. Client.connect() -- Null case
#     f. Client.finished()
#
# 2. Create server/client connections.
#     a. Server.setup()
#     b. Server.accept()
#     c. Server.finished()
#     d. Client.connect()
#     e. Client.finished()
#     f. Pipe.get_identity()
#
# 3. Send a single message.
# 4. Send complex messages.

# Isolated Pipes {{{1
def test_isolated_pipes():
    machine, port = 'localhost', 10236

    # First, test an isolated host.
    host = PickleHost(port, identity=1)

    # None of these commands should fail, even though there is no client.
    host.open()
    host.accept(); host.accept()
    host.close()

    # Once the host is closed, accept() should raise an assertion.
    try: host.accept()
    except AssertionError: pass
    else: raise AssertionError

    # Now test an isolated client.
    client = PickleClient(machine, port, identity=1)

    client.connect()
    client.connect()

    assert not client.finished()

# Connected Pipes {{{1
def test_connected_pipes():
    host, port = 'localhost', 10236

    def greet_client(self, pipe):
        assert pipe.get_identity() == 1

    def greet_server(self, pipe):
        assert pipe.get_identity() == 2

    server = PickleServer(port, seats=1, callback=greet_client)
    client = PickleClient(host, port, callback=greet_server)

    server.open()

    client.connect()    # Establish a connection.
    server.accept()     # Accept the connection and assign an identity.
    client.connect()    # Acknowledge the new connection.
    client.connect()    # Receive the assigned identity.

    assert server.finished()
    assert client.finished()

# Simple Messages {{{1
def test_simple_messages():
    host, port = 'localhost', 10236

    server = PickleServer(port, seats=1)
    client = PickleClient(host, port)

    server.setup()

    client.connect(); server.accept()
    client.connect(); client.connect()

    sender = client.get_pipe()
    receiver = client.get_pipes()[0]

    outbox = Outbox(); target = 1
    message = outbox.send_message()

    sender.register(target)      

    sender.send(target, message)
    sender.deliver()

    for tag, flavor, message in receiver.receive():
        inbox.receive(message)
        assert tag == 2, 1

    inbox.check(outbox)

# }}}1

# Many Messages {{{1

# Large Messages {{{1

# Partial Messages {{{1

# }}}1

if __name__ == '__main__':

    with TestInterface("Performing simple tests...", 3) as status:
        status.update();        test_isolated_pipes()
        status.update();        test_connected_pipes()
        status.update();        test_simple_messages()

    #with TestInterface("Performing rigorous tests...", 3) as status:
        #status.update();        test_many_messages()
        #status.update();        test_large_messages()
        #status.update();        test_partial_messages()

    TestInterface.report_success()
