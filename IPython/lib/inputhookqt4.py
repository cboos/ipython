# -*- coding: utf-8 -*-
"""
Qt4's inputhook support functions.

Author: Christian Boos
"""

#-----------------------------------------------------------------------------
#  Copyright (C) 2011  The IPython Development Team
#
#  Distributed under the terms of the BSD License.  The full license is in
#  the file COPYING, distributed as part of this software.
#-----------------------------------------------------------------------------

#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------

from IPython.external.qt_for_kernel import QtCore, QtGui
from IPython.lib.inputhook import stdin_ready

#-----------------------------------------------------------------------------
# Code
#-----------------------------------------------------------------------------

def make_qt4_app(app=None):
    """Ensure a Qt4 application is present.

    Parameters
    ----------
    app : Qt Application, optional.
        Running application to use.  If not given, we probe Qt for an
        existing application object, and create a new one if none is
        found.

    Returns
    -------
    A valid Qt Application (either the one given or the one found or
    created).
    """

    if app is None:
        app = QtCore.QCoreApplication.instance()
        if app is None:
            app = QtGui.QApplication([" "])
    return app

def inputhook_qt4():
    """PyOS_InputHook python hook for Qt4.

    Process pending Qt events and if there's no pending keyboard
    input, run the Qt event loop during a short period of time (50ms).
    """
    app = QtCore.QCoreApplication.instance()
    app.processEvents(QtCore.QEventLoop.AllEvents, 300)
    if not stdin_ready():
        timer = QtCore.QTimer()
        timer.timeout.connect(app.quit)
        while not stdin_ready():
            timer.start(50)
            app.exec_()
            timer.stop()
