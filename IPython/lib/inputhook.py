# coding: utf-8
"""
Inputhook management for GUI event loop integration.
"""

#-----------------------------------------------------------------------------
#  Copyright (C) 2008-2009  The IPython Development Team
#
#  Distributed under the terms of the BSD License.  The full license is in
#  the file COPYING, distributed as part of this software.
#-----------------------------------------------------------------------------

#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------

import ctypes
import os
import sys
import warnings

#-----------------------------------------------------------------------------
# Constants
#-----------------------------------------------------------------------------

# Constants for identifying the GUI toolkits.
GUI_WX = 'wx'
GUI_QT = 'qt'
GUI_QT4 = 'qt4'
GUI_GTK = 'gtk'
GUI_TK = 'tk'
GUI_OSX = 'osx'
GUI_GLUT = 'glut'
GUI_PYGLET = 'pyglet'
GUI_NONE = 'none' # i.e. disable

#-----------------------------------------------------------------------------
# Utilities
#-----------------------------------------------------------------------------

def _stdin_ready_posix():
    """Return True if there's something to read on stdin (posix version)."""
    infds, outfds, erfds = select.select([sys.stdin],[],[],0)
    return bool(infds)

def _stdin_ready_nt():
    """Return True if there's something to read on stdin (nt version)."""
    return msvcrt.kbhit()

def _stdin_ready_other():
    """Return True, assuming there's something to read on stdin."""
    return True #


def _ignore_CTRL_C_posix():
    """Ignore CTRL+C (SIGINT)."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)

def _allow_CTRL_C_posix():
    """Take CTRL+C into account (SIGINT)."""
    signal.signal(signal.SIGINT, signal.default_int_handler)

def _ignore_CTRL_C_other():
    """Ignore CTRL+C (not implemented)."""
    pass

def _allow_CTRL_C_other():
    """Take CTRL+C into account (not implemented)."""
    pass

if os.name == 'posix':
    import select
    import signal
    stdin_ready = _stdin_ready_posix
    ignore_CTRL_C = _ignore_CTRL_C_posix
    allow_CTRL_C = _allow_CTRL_C_posix
elif os.name == 'nt':
    import msvcrt
    stdin_ready = _stdin_ready_nt
    ignore_CTRL_C = _ignore_CTRL_C_other
    allow_CTRL_C = _allow_CTRL_C_other
else:
    stdin_ready = _stdin_ready_other
    ignore_CTRL_C = _ignore_CTRL_C_other
    allow_CTRL_C = _allow_CTRL_C_other


#-----------------------------------------------------------------------------
# Main InputHookManager class
#-----------------------------------------------------------------------------


class InputHookManager(object):
    """Manage PyOS_InputHook for different GUI toolkits.

    This class installs various hooks under ``PyOSInputHook`` to handle
    GUI event loop integration.
    """
    
    def __init__(self):
        self.PYFUNC = ctypes.PYFUNCTYPE(ctypes.c_int)
        self._apps = {}
        self._reset()

    def _reset(self):
        self._callback_pyfunctype = None
        self._callback = None
        self._installed = False
        self._current_gui = None
        self._inputhook_on_hold = None

    def get_pyos_inputhook(self):
        """Return the current PyOS_InputHook as a ctypes.c_void_p.

        TODO: mark it obsolete or remove it
        """
        return ctypes.c_void_p.in_dll(ctypes.pythonapi,"PyOS_InputHook")

    def get_pyos_inputhook_as_func(self):
        """Return the current PyOS_InputHook as a ctypes.PYFUNCYPE.

        TODO: mark it obsolete or remove it
        """
        return self.PYFUNC.in_dll(ctypes.pythonapi,"PyOS_InputHook")

    def _set_pyos_inputhook_as_void_p(self, void_p):
        """Assign a ctypes void_p to PyOS_InputHook.

        Return the current PyOS_InputHook callback.
        """
        pyos_inputhook_ptr = self.get_pyos_inputhook()
        original = self.get_pyos_inputhook_as_func()
        pyos_inputhook_ptr.value = void_p.value
        return original

    def set_safe_inputhook(self, callback):
        """Set PyOS_InputHook to callback and return the previous one.

        Such a callback will usually take care of running a GUI's
        native event loop until there's some keyboard input available
        (it can use `stdin_ready` for this).

        Notes
        -----
        The callback is appropriately wrapped into a function which
        deals with KeyboardInterrupt in a robust way:

          - an initial KeyboardInterrupt will interrupt the event loop
            and suspend the input hook,
          - if a second KeyboardInterrupt follows, it will be processed
            normally, clearing the prompt
          - when returning on the prompt (via CTRL+C or ENTER),
            the suspended input hook will be restored

        Returns
        -------

        The previously installed callback. If it was installed via
        `set_safe_inputhook`, the wrapped callback passed originally
        as parameter can be retrieved from the returned wrapper
        callback via the 'wrapped' attribute.

        """
        def safe_callback():
            """Execute callback passed to set_inputhook safely.

            Any KeyboardInterrupt exception raised during event loop
            processing will be intercepted and the input hook will be
            temporarily disabled until we re-enter the prompt (see
            `_restore_inputhook` below).
            """
            try:
                allow_CTRL_C()
                callback()
                ignore_CTRL_C()
            except KeyboardInterrupt:
                ignore_CTRL_C()
                self._inputhook_on_hold = safe_callback
                print("\nKeyboardInterrupt - event loop interrupted!"
                      "\n  * hit CTRL+C again to return to the prompt"
                      "\n    (event loop will then be resumed)"
                      "\n  * use '%%gui none' to disable the event loop"
                      " permanently"
                      "\n    and '%%gui %s' to re-enable it later\n" %
                      (self._current_gui or '...'))
                self.suspend_inputhook()
            return 0
        safe_callback.wrapped = callback

        # register _restore_inputhook() method as a 'pre_prompt_hook' (once)
        ip = get_ipython()
        if not hasattr(ip, '_InputHookManager_preprompthook'):
            ip.set_hook('pre_prompt_hook', self._restore_inputhook)
            ip._InputHookManager_preprompthook = True

        return self.set_inputhook(safe_callback)

    def set_inputhook(self, callback):
        """Set PyOS_InputHook to callback and return the previous one.

        Notes
        -----
        We must prevent the KeyboardInterrupt to be raised while the
        PyOS_InputHook is set to a Python ctypes callback. The
        callback may itself re-enable normal CTRL+C handling, see
        `ignore_CTRL_C` and `allow_CTRL_C`.

        """
        self._callback = callback
        self._callback_pyfunctype = self.PYFUNC(callback)
        ignore_CTRL_C()
        original = self._set_pyos_inputhook_as_void_p(
            ctypes.cast(self._callback_pyfunctype, ctypes.c_void_p))
        self._installed = True
        return original

    def clear_inputhook(self, app=None):
        """Set PyOS_InputHook to NULL and return the previous one.

        Parameters
        ----------
        app : optional, ignored
          This parameter is allowed only so that clear_inputhook() can be
          called with a similar interface as all the ``enable_*`` methods.  But
          the actual value of the parameter is ignored.  This uniform interface
          makes it easier to have user-level entry points in the main IPython
          app like :meth:`enable_gui`."""
        original = self.suspend_inputhook()
        self._reset()
        return original

    def suspend_inputhook(self):
        """Set PyOS_InputHook to NULL, but don't reset current state"""
        original = self._set_pyos_inputhook_as_void_p(ctypes.c_void_p(None))
        # it is now safe to restore normal CTRL+C processing
        allow_CTRL_C()
        return original

    def _restore_inputhook(self, ishell):
        """'pre_prompt_hook' used to restore a suspended inputhook.

        If a KeyboardInterrupt has been intercepted by a
        ''safe_callback'' input hook, the latter is temporarily
        disabled until the present pre-prompt hook is run.
        """
        if self._inputhook_on_hold:
            self.set_inputhook(self._inputhook_on_hold)
            self._inputhook_on_hold = None

    def clear_app_refs(self, gui=None):
        """Clear IPython's internal reference to an application instance.

        Whenever we create an app for a user on qt4 or wx, we hold a
        reference to the app.  This is needed because in some cases bad things
        can happen if a user doesn't hold a reference themselves.  This
        method is provided to clear the references we are holding.

        Parameters
        ----------
        gui : None or str
            If None, clear all app references.  If ('wx', 'qt4') clear
            the app for that toolkit.  References are not held for gtk or tk
            as those toolkits don't have the notion of an app.
        """
        if gui is None:
            self._apps = {}
        elif self._apps.has_key(gui):
            del self._apps[gui]

    def enable_wx(self, app=None):
        """Enable event loop integration with wxPython.

        Parameters
        ----------
        app : WX Application, optional.
            Running application to use.  If not given, we probe WX for an
            existing application object, and create a new one if none is found.

        Notes
        -----
        This methods sets the ``PyOS_InputHook`` for wxPython, which allows
        the wxPython to integrate with terminal based applications like
        IPython.

        If ``app`` is not given we probe for an existing one, and return it if
        found.  If no existing app is found, we create an :class:`wx.App` as
        follows::

            import wx
            app = wx.App(redirect=False, clearSigInt=False)
        """
        from IPython.lib.inputhookwx import inputhook_wx
        self.set_inputhook(inputhook_wx)
        self._current_gui = GUI_WX
        import wx
        if app is None:
            app = wx.GetApp()
        if app is None:
            app = wx.App(redirect=False, clearSigInt=False)
        app._in_event_loop = True
        self._apps[GUI_WX] = app
        return app

    def disable_wx(self):
        """Disable event loop integration with wxPython.

        This merely sets PyOS_InputHook to NULL.
        """
        if self._apps.has_key(GUI_WX):
            self._apps[GUI_WX]._in_event_loop = False
        self.clear_inputhook()

    def enable_qt4(self, app=None):
        """Enable event loop integration with PyQt4.
        
        Parameters
        ----------
        app : Qt Application, optional.
            Running application to use.  If not given, we probe Qt for an
            existing application object, and create a new one if none is found.

        Notes
        -----
        This methods sets the PyOS_InputHook for PyQt4, which allows
        the PyQt4 to integrate with terminal based applications like
        IPython.

        If ``app`` is not given we probe for an existing one, and return it if
        found.  If no existing app is found, we create an :class:`QApplication`
        as follows::

            from PyQt4 import QtCore
            app = QtGui.QApplication(sys.argv)
        """
        from IPython.lib.inputhookqt4 import inputhook_qt4, make_qt4_app
        app = make_qt4_app(app)
        self.set_safe_inputhook(inputhook_qt4)

        self._current_gui = GUI_QT4
        app._in_event_loop = True
        self._apps[GUI_QT4] = app
        return app

    def disable_qt4(self):
        """Disable event loop integration with PyQt4.

        This merely sets PyOS_InputHook to NULL.
        """
        if self._apps.has_key(GUI_QT4):
            self._apps[GUI_QT4]._in_event_loop = False
        self.clear_inputhook()

    def enable_gtk(self, app=None):
        """Enable event loop integration with PyGTK.

        Parameters
        ----------
        app : ignored
           Ignored, it's only a placeholder to keep the call signature of all
           gui activation methods consistent, which simplifies the logic of
           supporting magics.

        Notes
        -----
        This methods sets the PyOS_InputHook for PyGTK, which allows
        the PyGTK to integrate with terminal based applications like
        IPython.
        """
        import gtk
        try:
            gtk.set_interactive(True)
            self._current_gui = GUI_GTK
        except AttributeError:
            # For older versions of gtk, use our own ctypes version
            from IPython.lib.inputhookgtk import inputhook_gtk
            self.set_inputhook(inputhook_gtk)
            self._current_gui = GUI_GTK

    def disable_gtk(self):
        """Disable event loop integration with PyGTK.
        
        This merely sets PyOS_InputHook to NULL.
        """
        self.clear_inputhook()

    def enable_tk(self, app=None):
        """Enable event loop integration with Tk.

        Parameters
        ----------
        app : toplevel :class:`Tkinter.Tk` widget, optional.
            Running toplevel widget to use.  If not given, we probe Tk for an
            existing one, and create a new one if none is found.

        Notes
        -----
        If you have already created a :class:`Tkinter.Tk` object, the only
        thing done by this method is to register with the
        :class:`InputHookManager`, since creating that object automatically
        sets ``PyOS_InputHook``.
        """
        self._current_gui = GUI_TK
        if app is None:
            import Tkinter
            app = Tkinter.Tk()
            app.withdraw()
            self._apps[GUI_TK] = app
            return app

    def disable_tk(self):
        """Disable event loop integration with Tkinter.
        
        This merely sets PyOS_InputHook to NULL.
        """
        self.clear_inputhook()


    def enable_glut(self, app=None):
        """ Enable event loop integration with GLUT.

        Parameters
        ----------

        app : ignored
            Ignored, it's only a placeholder to keep the call signature of all
            gui activation methods consistent, which simplifies the logic of
            supporting magics.

        Notes
        -----

        This methods sets the PyOS_InputHook for GLUT, which allows the GLUT to
        integrate with terminal based applications like IPython. Due to GLUT
        limitations, it is currently not possible to start the event loop
        without first creating a window. You should thus not create another
        window but use instead the created one. See 'gui-glut.py' in the
        docs/examples/lib directory.
        
        The default screen mode is set to:
        glut.GLUT_DOUBLE | glut.GLUT_RGBA | glut.GLUT_DEPTH
        """

        import OpenGL.GLUT as glut
        from IPython.lib.inputhookglut import glut_display_mode, \
                                              glut_close, glut_display, \
                                              glut_idle, inputhook_glut

        if not self._apps.has_key( GUI_GLUT ):
            glut.glutInit( sys.argv )
            glut.glutInitDisplayMode( glut_display_mode )
            # This is specific to freeglut
            if bool(glut.glutSetOption):
                glut.glutSetOption( glut.GLUT_ACTION_ON_WINDOW_CLOSE,
                                    glut.GLUT_ACTION_GLUTMAINLOOP_RETURNS )
            glut.glutCreateWindow( sys.argv[0] )
            glut.glutReshapeWindow( 1, 1 )
            glut.glutHideWindow( )
            glut.glutWMCloseFunc( glut_close )
            glut.glutDisplayFunc( glut_display )
            glut.glutIdleFunc( glut_idle )
        else:
            glut.glutWMCloseFunc( glut_close )
            glut.glutDisplayFunc( glut_display )
            glut.glutIdleFunc( glut_idle)
        self.set_inputhook( inputhook_glut )
        self._current_gui = GUI_GLUT
        self._apps[GUI_GLUT] = True


    def disable_glut(self):
        """Disable event loop integration with glut.
        
        This sets PyOS_InputHook to NULL and set the display function to a
        dummy one and set the timer to a dummy timer that will be triggered
        very far in the future.
        """
        import OpenGL.GLUT as glut
        from glut_support import glutMainLoopEvent

        glut.glutHideWindow() # This is an event to be processed below
        glutMainLoopEvent()
        self.clear_inputhook()

    def enable_pyglet(self, app=None):
        """Enable event loop integration with pyglet.

        Parameters
        ----------
        app : ignored
           Ignored, it's only a placeholder to keep the call signature of all
           gui activation methods consistent, which simplifies the logic of
           supporting magics.

        Notes
        -----
        This methods sets the ``PyOS_InputHook`` for pyglet, which allows
        pyglet to integrate with terminal based applications like
        IPython.

        """
        import pyglet
        from IPython.lib.inputhookpyglet import inputhook_pyglet
        self.set_inputhook(inputhook_pyglet)
        self._current_gui = GUI_PYGLET
        return app

    def disable_pyglet(self):
        """Disable event loop integration with pyglet.

        This merely sets PyOS_InputHook to NULL.
        """
        self.clear_inputhook()

    def current_gui(self):
        """Return a string indicating the currently active GUI or None."""
        return self._current_gui

inputhook_manager = InputHookManager()

enable_wx = inputhook_manager.enable_wx
disable_wx = inputhook_manager.disable_wx
enable_qt4 = inputhook_manager.enable_qt4
disable_qt4 = inputhook_manager.disable_qt4
enable_gtk = inputhook_manager.enable_gtk
disable_gtk = inputhook_manager.disable_gtk
enable_tk = inputhook_manager.enable_tk
disable_tk = inputhook_manager.disable_tk
enable_glut = inputhook_manager.enable_glut
disable_glut = inputhook_manager.disable_glut
enable_pyglet = inputhook_manager.enable_pyglet
disable_pyglet = inputhook_manager.disable_pyglet
clear_inputhook = inputhook_manager.clear_inputhook
set_inputhook = inputhook_manager.set_inputhook
current_gui = inputhook_manager.current_gui
clear_app_refs = inputhook_manager.clear_app_refs


# Convenience function to switch amongst them
def enable_gui(gui=None, app=None):
    """Switch amongst GUI input hooks by name.

    This is just a utility wrapper around the methods of the InputHookManager
    object.

    Parameters
    ----------
    gui : optional, string or None
      If None (or 'none'), clears input hook, otherwise it must be one
      of the recognized GUI names (see ``GUI_*`` constants in module).

    app : optional, existing application object.
      For toolkits that have the concept of a global app, you can supply an
      existing one.  If not given, the toolkit will be probed for one, and if
      none is found, a new one will be created.  Note that GTK does not have
      this concept, and passing an app if `gui`=="GTK" will raise an error.

    Returns
    -------
    The output of the underlying gui switch routine, typically the actual
    PyOS_InputHook wrapper object or the GUI toolkit app created, if there was
    one.
    """
    guis = {None: clear_inputhook,
            GUI_NONE: clear_inputhook,
            GUI_OSX: lambda app=False: None,
            GUI_TK: enable_tk,
            GUI_GTK: enable_gtk,
            GUI_WX: enable_wx,
            GUI_QT: enable_qt4, # qt3 not supported
            GUI_QT4: enable_qt4,
            GUI_GLUT: enable_glut,
            GUI_PYGLET: enable_pyglet,
            }
    try:
        gui_hook = guis[gui]
    except KeyError:
        e = "Invalid GUI request %r, valid ones are:%s" % (gui, guis.keys())
        raise ValueError(e)
    return gui_hook(app)

