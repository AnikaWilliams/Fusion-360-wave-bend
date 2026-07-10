# WaveBend.py — add-in entry point (structure follows Fusion's official template;
# no modification needed here unless the general structure changes).
from . import commands
from .lib import fusionAddInUtils as futil


def run(context):
    try:
        # Runs the start function in each command defined in commands/__init__.py
        commands.start()
    except:
        futil.handle_error('run')


def stop(context):
    try:
        # Remove all event handlers this add-in created, then stop each command.
        futil.clear_handlers()
        commands.stop()
    except:
        futil.handle_error('stop')
