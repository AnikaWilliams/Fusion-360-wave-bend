# Commands registered by this add-in. Fusion calls start()/stop() on each.
from .waveBendCmd import entry as waveBendCmd

commands = [
    waveBendCmd,
]


def start():
    for command in commands:
        command.start()


def stop():
    for command in commands:
        command.stop()
