#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright Martin Manns
# Distributed under the terms of the GNU General Public License

# --------------------------------------------------------------------
# pyspread is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pyspread is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pyspread.  If not, see <http://www.gnu.org/licenses/>.
# --------------------------------------------------------------------


"""
_grid_actions.py
=======================

Module for main main grid level actions.
All non-trivial functionality that results from grid actions
and belongs to the grid only goes here.

Provides:
---------
  1. FileActions: Actions which affect the open grid
  2. TableRowActionsMixin: Mixin for TableActions
  3. TableColumnActionsMixin: Mixin for TableActions
  4. TableTabActionsMixin: Mixin for TableActions
  5. TableActions: Actions which affect table
  6. MacroActions: Actions on macros
  7. UnRedoActions: Actions on the undo redo system
  8. GridActions: Actions on the grid as a whole
  9. SelectionActions: Actions on the grid selection
  10. FindActions: Actions for finding and replacing
  11. AllGridActions: All grid actions as a bundle


"""


import ast
import itertools
import os
import os.path
import src.lib.i18n as i18n
import shutil
import tempfile
import types

try:
    import xlrd
except ImportError:
    xlrd = None

try:
    import xlwt
except ImportError:
    xlwt = None

try:
    import odf
except ImportError:
    odf = None

import wx

from src.config import config
from src.sysvars import get_default_font, is_gtk
from src.gui._grid_table import GridTable
from src.interfaces.pys import Pys
from src.interfaces.xls import Xls
try:
    from src.interfaces.ods import Ods
except ImportError:
    Ods = None

try:
    from src.lib.gpg import sign, verify
    GPG_PRESENT = True

except ImportError:
    GPG_PRESENT = False

from src.lib.selection import Selection
from src.lib.fileio import AOpen, Bz2AOpen

from src.actions._main_window_actions import Actions
from src.actions._grid_cell_actions import CellActions

from src.gui._events import post_command_event

# Use ugettext instead of getttext to avoid unicode errors
_ = i18n.language.ugettext


class FileActions(Actions):
    """File actions on the grid"""

    def __init__(self, grid):
        Actions.__init__(self, grid)

        # The pys file version that are expected.
        # The latter version is created
        self.pys_versions = ["0.1"]

        self.saving = False

        self.main_window.Bind(self.EVT_CMD_GRID_ACTION_OPEN, self.open)
        self.main_window.Bind(self.EVT_CMD_GRID_ACTION_SAVE, self.save)

        self.type2interface = {
            "pys": Pys,
            "pysu": Pys,
            "xls": Xls,
            "xlsx": Xls,
            "ods": Ods,
        }

    def _is_aborted(self, cycle, statustext, total_elements=None, freq=None):
        """Displays progress and returns True if abort

        Parameters
        ----------

        cycle: Integer
        \tThe current operation cycle
        statustext: String
        \tLeft text in statusbar to be displayed
        total_elements: Integer:
        \tThe number of elements that have to be processed
        freq: Integer, defaults to None
        \tNo. operations between two abort possibilities, 1000 if None

        """

        if total_elements is None:
            statustext += _("{nele} elements processed. Press <Esc> to abort.")
        else:
            statustext += _("{nele} of {totalele} elements processed. "
                            "Press <Esc> to abort.")

        if freq is None:
            show_msg = False
            freq = 1000
        else:
            show_msg = True

        # Show progress in statusbar each freq (1000) cells
        if cycle % freq == 0:
            if show_msg:
                text = statustext.format(nele=cycle, totalele=total_elements)
                try:
                    post_command_event(self.main_window, self.StatusBarMsg,
                                       text=text)
                except TypeError:
                    # The main window does not exist any more
                    pass

            # Now wait for the statusbar update to be written on screen
            if is_gtk():
                try:
                    wx.Yield()
                except:
                    pass

            # Abort if we have to
            if self.need_abort:
                # We have to abort`
                return True

        # Continue
        return False

    def validate_signature(self, filename):
        """Returns True if a valid signature is present for filename"""

        if not GPG_PRESENT:
            return False

        sigfilename = filename + '.sig'

        try:
            with open(sigfilename):
                pass

        except IOError:
            # Signature file does not exist
            return False

        # Check if the sig is valid for the sigfile
        # TODO: Check for whitespace in filepaths
        return verify(sigfilename, filename)

    def enter_safe_mode(self):
        """Enters safe mode"""

        self.code_array.safe_mode = True

    def leave_safe_mode(self):
        """Leaves safe mode"""

        self.code_array.safe_mode = False

        # Clear result cache
        self.code_array.result_cache.clear()

        # Execute macros
        self.main_window.actions.execute_macros()

        post_command_event(self.main_window, self.SafeModeExitMsg)

    def approve(self, filepath):
        """Sets safe mode if signature missing of invalid"""

        try:
            signature_valid = self.validate_signature(filepath)

        except ValueError:
            # GPG is not installed
            signature_valid = False

        if signature_valid:
            self.leave_safe_mode()
            post_command_event(self.main_window, self.SafeModeExitMsg)

            statustext = _("Valid signature found. File is trusted.")
            post_command_event(self.main_window, self.StatusBarMsg,
                               text=statustext)

        else:
            self.enter_safe_mode()
            post_command_event(self.main_window, self.SafeModeEntryMsg)

            statustext = \
                _("File is not properly signed. Safe mode "
                  "activated. Select File -> Approve to leave safe mode.")
            post_command_event(self.main_window, self.StatusBarMsg,
                               text=statustext)

    def clear_globals_reload_modules(self):
        """Clears globals and reloads modules"""

        self.code_array.clear_globals()
        self.code_array.reload_modules()

        # Clear result cache
        self.code_array.result_cache.clear()

    def _get_file_version(self, infile):
        """Returns infile version string."""

        # Determine file version
        for line1 in infile:
            if line1.strip() != "[Pyspread save file version]":
                raise ValueError(_("File format unsupported."))
            break

        for line2 in infile:
            return line2.strip()

    def clear(self, shape=None):
        """Empties grid and sets shape to shape

        Clears all attributes, row heights, column withs and frozen states.
        Empties undo/redo list and caches. Empties globals.

        Properties
        ----------

        shape: 3-tuple of Integer, defaults to None
        \tTarget shape of grid after clearing all content.
        \tShape unchanged if None

        """

        # Without setting this explicitly, the cursor is set too late
        self.grid.actions.cursor = 0, 0, 0
        self.grid.current_table = 0

        post_command_event(self.main_window.grid, self.GotoCellMsg,
                           key=(0, 0, 0))

        # Clear cells
        self.code_array.dict_grid.clear()

        # Clear attributes
        del self.code_array.dict_grid.cell_attributes[:]

        if shape is not None:
            # Set shape
            self.code_array.shape = shape

        # Clear row heights and column widths
        self.code_array.row_heights.clear()
        self.code_array.col_widths.clear()

        # Clear macros
        self.code_array.macros = ""

        # Clear caches
        self.code_array.unredo.reset()
        self.code_array.result_cache.clear()

        # Clear globals
        self.code_array.clear_globals()
        self.code_array.reload_modules()

    def open(self, event):
        """Opens a file that is specified in event.attr

        Parameters
        ----------
        event.attr: Dict
        \tkey filepath contains file path of file to be loaded
        \tkey filetype contains file type of file to be loaded
        \tFiletypes can be pys, pysu, xls

        """

        filepath = event.attr["filepath"]
        try:
            filetype = event.attr["filetype"]

        except KeyError:
            try:
                file_ext = filepath.strip().split(".")[-1]
            except:
                file_ext = None

            if file_ext in ["pys", "pysu", "xls", "xlsx", "ods"]:
                filetype = file_ext
            else:
                filetype = "pys"

        type2opener = {
            "pys": (Bz2AOpen, [filepath, "r"], {"main_window":
                                                self.main_window}),
            "pysu": (AOpen, [filepath, "r"], {"main_window": self.main_window})
        }

        if xlrd is not None:
            type2opener["xls"] = \
                (xlrd.open_workbook, [filepath], {"formatting_info": True})

            type2opener["xlsx"] = \
                (xlrd.open_workbook, [filepath], {"formatting_info": False})

        if odf is not None and Ods is not None:
            type2opener["ods"] = (open, [filepath, "rb"], {})

        # Specify the interface that shall be used
        opener, op_args, op_kwargs = type2opener[filetype]
        Interface = self.type2interface[filetype]

        # Set state for file open
        self.opening = True

        try:
            with opener(*op_args, **op_kwargs) as infile:
                # Make loading safe
                self.approve(filepath)

                # Disable undo
                self.grid.code_array.unredo.active = True
                if xlrd:
                    # XLRD is loaded so it's safe to use its Exception type
                    try:
                        wx.BeginBusyCursor()
                        self.grid.Disable()
                        self.clear()
                        interface = Interface(self.grid.code_array, infile)
                        interface.to_code_array()

                    except (ValueError, xlrd.biffh.XLRDError), err:
                        post_command_event(self.main_window, self.StatusBarMsg,
                                        text=str(err))

                    finally:
                        self.grid.GetTable().ResetView()
                        post_command_event(self.main_window, self.ResizeGridMsg,
                                        shape=self.grid.code_array.shape)
                        self.grid.Enable()
                        wx.EndBusyCursor()
                else:
                    # XLRD is not loaded so it's Exception type is not needed and should not be loaded
                    try:
                        wx.BeginBusyCursor()
                        self.grid.Disable()
                        self.clear()
                        interface = Interface(self.grid.code_array, infile)
                        interface.to_code_array()

                    except ValueError, err:
                        post_command_event(self.main_window, self.StatusBarMsg,
                                        text=str(err))

                    finally:
                        self.grid.GetTable().ResetView()
                        post_command_event(self.main_window, self.ResizeGridMsg,
                                        shape=self.grid.code_array.shape)
                        self.grid.Enable()
                        wx.EndBusyCursor()

                # Execute macros
                self.main_window.actions.execute_macros()

                # Enable undo again
                self.grid.code_array.unredo.active = False

                self.grid.GetTable().ResetView()
                self.grid.ForceRefresh()

                # File sucessfully opened. Approve again to show status.
                self.approve(filepath)

                # Change current directory to file directory
                filedir = os.path.dirname(filepath)
                os.chdir(filedir)

        except IOError, err:
            txt = _("Error opening file {filepath}:").format(filepath=filepath)
            txt += " " + str(err)
            post_command_event(self.main_window, self.StatusBarMsg, text=txt)

            return False

        except EOFError:
            # Normally on empty grids
            pass

        finally:
            # Unset state for file open
            self.opening = False

    def sign_file(self, filepath):
        """Signs file if possible"""

        if not GPG_PRESENT:
            return

        signed_data = sign(filepath)
        signature = signed_data.data

        if signature is None or not signature:
            statustext = _('Error signing file. ') + signed_data.stderr
            try:
                post_command_event(self.main_window, self.StatusBarMsg,
                                   text=statustext)
            except TypeError:
                # The main window does not exist any more
                pass

            return

        with open(filepath + '.sig', 'wb') as signfile:
            signfile.write(signature)

        # Statustext differs if a save has occurred

        if self.code_array.safe_mode:
            statustext = _('File saved and signed')
        else:
            statustext = _('File signed')

        try:
            post_command_event(self.main_window, self.StatusBarMsg,
                               text=statustext)
        except TypeError:
            # The main window does not exist any more
            pass

    def _set_save_states(self):
        """Sets application save states"""

        wx.BeginBusyCursor()
        self.saving = True
        self.grid.Disable()

    def _release_save_states(self):
        """Releases application save states"""

        self.saving = False
        self.grid.Enable()
        wx.EndBusyCursor()

        # Mark content as unchanged
        try:
            post_command_event(self.main_window, self.ContentChangedMsg,
                               changed=False)
        except TypeError:
            # The main window does not exist any more
            pass

    def _move_tmp_file(self, tmpfilepath, filepath):
        """Moves tmpfile over file after saving is finished

        Parameters
        ----------

        filepath: String
        \tTarget file path for xls file
        tmpfilepath: String
        \tTemporary file file path for xls file

        """

        try:
            shutil.move(tmpfilepath, filepath)

        except OSError, err:
            # No tmp file present
            post_command_event(self.main_window, self.StatusBarMsg, text=err)

    def _save_xls(self, filepath):
        """Saves file as xls workbook

        Parameters
        ----------

        filepath: String
        \tTarget file path for xls file

        """

        Interface = self.type2interface["xls"]

        workbook = xlwt.Workbook()
        interface = Interface(self.grid.code_array, workbook)
        interface.from_code_array()

        try:
            workbook.save(filepath)

        except IOError, err:
            try:
                post_command_event(self.main_window, self.StatusBarMsg,
                                   text=err)
            except TypeError:
                # The main window does not exist any more
                pass

    def _save_pys(self, filepath):
        """Saves file as pys file and returns True if save success

        Parameters
        ----------

        filepath: String
        \tTarget file path for xls file

        """

        try:
            with Bz2AOpen(filepath, "wb",
                          main_window=self.main_window) as outfile:
                interface = Pys(self.grid.code_array, outfile)
                interface.from_code_array()

        except (IOError, ValueError), err:
            try:
                post_command_event(self.main_window, self.StatusBarMsg,
                                   text=err)
                return
            except TypeError:
                # The main window does not exist any more
                pass

        return not outfile.aborted

    def _save_pysu(self, filepath):
        """Saves file as pys file and returns True if save success

        Parameters
        ----------

        filepath: String
        \tTarget file path for xls file

        """

        try:
            with AOpen(filepath, "wb",
                       main_window=self.main_window) as outfile:
                interface = Pys(self.grid.code_array, outfile)
                interface.from_code_array()

        except (IOError, ValueError), err:
            try:
                post_command_event(self.main_window, self.StatusBarMsg,
                                   text=err)
                return
            except TypeError:
                # The main window does not exist any more
                pass

        return not outfile.aborted

    def _save_sign(self, filepath):
        """Sign so that the new file may be retrieved without safe mode"""

        if self.code_array.safe_mode:
            msg = _("File saved but not signed because it is unapproved.")
            try:
                post_command_event(self.main_window, self.StatusBarMsg,
                                   text=msg)
            except TypeError:
                # The main window does not exist any more
                pass

        else:
            self.sign_file(filepath)

    def save(self, event):
        """Saves a file that is specified in event.attr

        Parameters
        ----------
        event.attr: Dict
        \tkey filepath contains file path of file to be saved

        """

        filepath = event.attr["filepath"]

        try:
            filetype = event.attr["filetype"]
        except KeyError:
            filetype = "pys"

        # If saving is already in progress abort
        if self.saving:
            return

        # Use tmpfile to make sure that old save file does not get lost
        # on abort save

        __, tmpfilepath = tempfile.mkstemp()

        if filetype == "xls":
            self._set_save_states()
            self._save_xls(tmpfilepath)
            self._move_tmp_file(tmpfilepath, filepath)
            self._release_save_states()

        elif filetype == "pys" or filetype == "all":
            self._set_save_states()
            if self._save_pys(tmpfilepath):
                # Writing was successful
                self._move_tmp_file(tmpfilepath, filepath)
                self._save_sign(filepath)
            self._release_save_states()

        elif filetype == "pysu":
            self._set_save_states()
            if self._save_pysu(tmpfilepath):
                # Writing was successful
                self._move_tmp_file(tmpfilepath, filepath)
                self._save_sign(filepath)
            self._release_save_states()

        else:
            os.remove(tmpfilepath)
            msg = "Filetype {filetype} unknown.".format(filetype=filetype)
            raise ValueError(msg)

        try:
            os.remove(tmpfilepath)
        except OSError:
            pass


class TableRowActionsMixin(Actions):
    """Table row controller actions"""

    def set_row_height(self, row, height):
        """Sets row height and marks grid as changed"""

        # Mark content as changed
        post_command_event(self.main_window, self.ContentChangedMsg,
                           changed=True)

        tab = self.grid.current_table

        self.code_array.set_row_height(row, tab, height)
        self.grid.SetRowSize(row, height)

    def insert_rows(self, row, no_rows=1):
        """Adds no_rows rows before row, appends if row > maxrows

        and marks grid as changed

        """

        # Mark content as changed
        post_command_event(self.main_window, self.ContentChangedMsg,
                           changed=True)

        tab = self.grid.current_table

        self.code_array.insert(row, no_rows, axis=0, tab=tab)

    def delete_rows(self, row, no_rows=1):
        """Deletes no_rows rows and marks grid as changed"""

        # Mark content as changed
        post_command_event(self.main_window, self.ContentChangedMsg,
                           changed=True)

        tab = self.grid.current_table

        try:
            self.code_array.delete(row, no_rows, axis=0, tab=tab)

        except ValueError, err:
            post_command_event(self.main_window, self.StatusBarMsg,
                               text=err.message)


class TableColumnActionsMixin(Actions):
    """Table column controller actions"""

    def set_col_width(self, col, width):
        """Sets column width and marks grid as changed"""

        # Mark content as changed
        post_command_event(self.main_window, self.ContentChangedMsg,
                           changed=True)

        tab = self.grid.current_table

        self.code_array.set_col_width(col, tab, width)
        self.grid.SetColSize(col, width)

    def insert_cols(self, col, no_cols=1):
        """Adds no_cols columns before col, appends if col > maxcols

        and marks grid as changed

        """

        # Mark content as changed
        post_command_event(self.main_window, self.ContentChangedMsg,
                           changed=True)

        tab = self.grid.current_table

        self.code_array.insert(col, no_cols, axis=1, tab=tab)

    def delete_cols(self, col, no_cols=1):
        """Deletes no_cols column and marks grid as changed"""

        # Mark content as changed
        post_command_event(self.main_window, self.ContentChangedMsg,
                           changed=True)

        tab = self.grid.current_table

        try:
            self.code_array.delete(col, no_cols, axis=1, tab=tab)

        except ValueError, err:
            post_command_event(self.main_window, self.StatusBarMsg,
                               text=err.message)


class TableTabActionsMixin(Actions):
    """Table tab controller actions"""

    def insert_tabs(self, tab, no_tabs=1):
        """Adds no_tabs tabs before table, appends if tab > maxtabs

        and marks grid as changed

        """

        # Mark content as changed
        post_command_event(self.main_window, self.ContentChangedMsg,
                           changed=True)

        self.code_array.insert(tab, no_tabs, axis=2)

        # Update TableChoiceIntCtrl
        shape = self.grid.code_array.shape
        post_command_event(self.main_window, self.ResizeGridMsg, shape=shape)

    def delete_tabs(self, tab, no_tabs=1):
        """Deletes no_tabs tabs and marks grid as changed"""

        # Mark content as changed
        post_command_event(self.main_window, self.ContentChangedMsg,
                           changed=True)

        try:
            self.code_array.delete(tab, no_tabs, axis=2)

            # Update TableChoiceIntCtrl
            shape = self.grid.code_array.shape
            post_command_event(self.main_window, self.ResizeGridMsg,
                               shape=shape)

        except ValueError, err:
            post_command_event(self.main_window, self.StatusBarMsg,
                               text=err.message)


class TableActions(TableRowActionsMixin, TableColumnActionsMixin,
                   TableTabActionsMixin):
    """Table controller actions"""

    def __init__(self, grid):
        TableRowActionsMixin.__init__(self, grid)
        TableColumnActionsMixin.__init__(self, grid)
        TableTabActionsMixin.__init__(self, grid)

        # Action states

        self.pasting = False

        # Bindings

        self.main_window.Bind(wx.EVT_KEY_DOWN, self.on_key)

    def on_key(self, event):
        """Sets abort if pasting and if escape is pressed"""

        # If paste is running and Esc is pressed then we need to abort

        if event.GetKeyCode() == wx.WXK_ESCAPE and \
           self.pasting or self.grid.actions.saving:
            self.need_abort = True

        event.Skip()

    def _get_full_key(self, key):
        """Returns full key even if table is omitted"""

        length = len(key)

        if length == 3:
            return key

        elif length == 2:
            row, col = key
            tab = self.grid.current_table
            return row, col, tab

        else:
            msg = _("Key length {length}  not in (2, 3)").format(length=length)
            raise ValueError(msg)

    def _abort_paste(self):
        """Aborts import"""

        statustext = _("Paste aborted.")
        post_command_event(self.main_window, self.StatusBarMsg,
                           text=statustext)

        self.pasting = False
        self.need_abort = False

    def _show_final_overflow_message(self, row_overflow, col_overflow):
        """Displays overflow message after import in statusbar"""

        if row_overflow and col_overflow:
            overflow_cause = _("rows and columns")
        elif row_overflow:
            overflow_cause = _("rows")
        elif col_overflow:
            overflow_cause = _("columns")
        else:
            raise AssertionError(_("Import cell overflow missing"))

        statustext = \
            _("The imported data did not fit into the grid {cause}. "
              "It has been truncated. Use a larger grid for full import.").\
            format(cause=overflow_cause)
        post_command_event(self.main_window, self.StatusBarMsg,
                           text=statustext)

    def _show_final_paste_message(self, tl_key, no_pasted_cells):
        """Show actually pasted number of cells"""

        plural = "" if no_pasted_cells == 1 else _("s")

        statustext = _("{ncells} cell{plural} pasted at cell {topleft}").\
            format(ncells=no_pasted_cells, plural=plural, topleft=tl_key)

        post_command_event(self.main_window, self.StatusBarMsg,
                           text=statustext)

    def paste_to_current_cell(self, tl_key, data, freq=None):
        """Pastes data into grid from top left cell tl_key

        Parameters
        ----------

        ul_key: Tuple
        \key of top left cell of paste area
        data: iterable of iterables where inner iterable returns string
        \tThe outer iterable represents rows
        freq: Integer, defaults to None
        \tStatus message frequency

        """

        self.pasting = True

        grid_rows, grid_cols, __ = self.grid.code_array.shape

        self.need_abort = False

        tl_row, tl_col, tl_tab = self._get_full_key(tl_key)

        row_overflow = False
        col_overflow = False

        no_pasted_cells = 0

        for src_row, row_data in enumerate(data):
            target_row = tl_row + src_row

            if self.grid.actions._is_aborted(src_row, _("Pasting cells... "),
                                             freq=freq):
                self._abort_paste()
                return False

            # Check if rows fit into grid
            if target_row >= grid_rows:
                row_overflow = True
                break

            for src_col, cell_data in enumerate(row_data):
                target_col = tl_col + src_col

                if target_col >= grid_cols:
                    col_overflow = True
                    break

                if cell_data is not None:
                    # Is only None if pasting into selection
                    key = target_row, target_col, tl_tab

                    try:
                        # Set cell but do not mark unredo
                        # before pasting is finished

                        self.grid.code_array.__setitem__(key, cell_data,
                                                         mark_unredo=False)
                        no_pasted_cells += 1
                    except KeyError:
                        pass

        if row_overflow or col_overflow:
            self._show_final_overflow_message(row_overflow, col_overflow)

        else:
            self._show_final_paste_message(tl_key, no_pasted_cells)

        if no_pasted_cells:
            # If cells have been pasted mark unredo operation
            self.grid.code_array.unredo.mark()

        self.pasting = False

    def selection_paste_data_gen(self, selection, data, freq=None):
        """Generator that yields data for selection paste"""

        (bb_top, bb_left), (bb_bottom, bb_right) = \
            selection.get_grid_bbox(self.grid.code_array.shape)
        bbox_height = bb_bottom - bb_top + 1
        bbox_width = bb_right - bb_left + 1

        for row, row_data in enumerate(itertools.cycle(data)):
            # Break if row is not in selection bbox
            if row >= bbox_height:
                break

            # Duplicate row data if selection is wider than row data
            row_data = list(row_data)
            duplicated_row_data = row_data * (bbox_width // len(row_data) + 1)
            duplicated_row_data = duplicated_row_data[:bbox_width]

            for col in xrange(len(duplicated_row_data)):
                if (bb_top, bb_left + col) not in selection:
                    duplicated_row_data[col] = None

            yield duplicated_row_data

    def paste_to_selection(self, selection, data, freq=None):
        """Pastes data into grid selection"""

        (bb_top, bb_left), (bb_bottom, bb_right) = \
            selection.get_grid_bbox(self.grid.code_array.shape)
        adjusted_data = self.selection_paste_data_gen(selection, data)
        self.paste_to_current_cell((bb_top, bb_left), adjusted_data, freq=freq)

    def paste(self, tl_key, data, freq=None):
        """Pastes data into grid, marks grid changed

        If no selection is present, data is pasted starting with current cell
        If a selection is present, data is pasted fully if the selection is
        smaller. If the selection is larger then data is duplicated.

        Parameters
        ----------

        ul_key: Tuple
        \key of top left cell of paste area
        data: iterable of iterables where inner iterable returns string
        \tThe outer iterable represents rows
        freq: Integer, defaults to None
        \tStatus message frequency

        """

        # Get selection bounding box

        selection = self.get_selection()

        # Mark content as changed
        post_command_event(self.main_window, self.ContentChangedMsg,
                           changed=True)

        if selection:
            # There is a selection.  Paste into it
            self.paste_to_selection(selection, data, freq=freq)
        else:
            # There is no selection.  Paste from top left cell.
            self.paste_to_current_cell(tl_key, data, freq=freq)

    def change_grid_shape(self, shape):
        """Grid shape change event handler, marks content as changed"""

        # Mark content as changed
        post_command_event(self.main_window, self.ContentChangedMsg,
                           changed=True)

        self.grid.code_array.shape = shape

        # Update TableChoiceIntCtrl
        post_command_event(self.main_window, self.ResizeGridMsg, shape=shape)

        # Clear caches
        self.code_array.unredo.reset()
        self.code_array.result_cache.clear()

    def replace_cells(self, key, sorted_row_idxs):
        """Replaces cells in current selection so that they are sorted"""

        row, col, tab = key

        new_keys = {}
        del_keys = []

        selection = self.grid.actions.get_selection()

        for __row, __col, __tab in self.grid.code_array:
            if __tab == tab and \
               (not selection or (__row, __col) in selection):
                new_row = sorted_row_idxs.index(__row)
                if __row != new_row:
                    new_keys[(new_row, __col, __tab)] = \
                        self.grid.code_array((__row, __col, __tab))
                    del_keys.append((__row, __col, __tab))

        for key in del_keys:
            self.grid.code_array.pop(key, mark_unredo=False)

        for key in new_keys:
            self.grid.code_array.__setitem__(key, new_keys[key],
                                             mark_unredo=False)

        self.grid.code_array.unredo.mark()

    def sort_ascending(self, key):
        """Sorts selection (or grid if none) corresponding to column of key"""

        row, col, tab = key

        scells = self.grid.code_array[:, col, tab]

        def sorter(i):
            sorted_ele = scells[i]
            return sorted_ele is None, sorted_ele

        sorted_row_idxs = sorted(xrange(len(scells)), key=sorter)

        self.replace_cells(key, sorted_row_idxs)

        self.grid.ForceRefresh()

    def sort_descending(self, key):
        """Sorts inversely selection (or grid if none)

        corresponding to column of key

        """

        row, col, tab = key

        scells = self.grid.code_array[:, col, tab]
        sorted_row_idxs = sorted(xrange(len(scells)), key=scells.__getitem__)
        sorted_row_idxs.reverse()

        self.replace_cells(key, sorted_row_idxs)

        self.grid.ForceRefresh()


class UnRedoActions(Actions):
    """Undo and redo operations"""

    def undo(self):
        """Calls undo in model.code_array.unredo, marks content as changed"""

        # Mark content as changed
        post_command_event(self.main_window, self.ContentChangedMsg,
                           changed=True)

        self.grid.code_array.unredo.undo()

    def redo(self):
        """Calls redo in model.code_array.unredo, marks content as changed"""

        # Mark content as changed
        post_command_event(self.main_window, self.ContentChangedMsg,
                           changed=True)

        self.grid.code_array.unredo.redo()


class GridActions(Actions):
    """Grid level grid actions"""

    def __init__(self, grid):
        Actions.__init__(self, grid)

        self.code_array = grid.code_array

        self.prev_rowcol = []  # Last mouse over cell

        self.main_window.Bind(self.EVT_CMD_GRID_ACTION_NEW, self.new)
        self.main_window.Bind(self.EVT_CMD_GRID_ACTION_TABLE_SWITCH,
                              self.switch_to_table)

    def new(self, event):
        """Creates a new spreadsheet. Expects code_array in event."""

        # Grid table handles interaction to code_array

        self.grid.actions.clear(event.shape)

        _grid_table = GridTable(self.grid, self.grid.code_array)
        self.grid.SetTable(_grid_table, True)

        # Update toolbars
        self.grid.update_entry_line()
        self.grid.update_attribute_toolbar()

    # Zoom actions

    def _zoom_rows(self, zoom):
        """Zooms grid rows"""

        self.grid.SetDefaultRowSize(self.grid.std_row_size * zoom,
                                    resizeExistingRows=True)
        self.grid.SetRowLabelSize(self.grid.row_label_size * zoom)

        for row, tab in self.code_array.row_heights:
            if tab == self.grid.current_table and \
               row < self.grid.code_array.shape[0]:
                zoomed_row_size = \
                    self.code_array.row_heights[(row, tab)] * zoom
                self.grid.SetRowSize(row, zoomed_row_size)

    def _zoom_cols(self, zoom):
        """Zooms grid columns"""

        self.grid.SetDefaultColSize(self.grid.std_col_size * zoom,
                                    resizeExistingCols=True)
        self.grid.SetColLabelSize(self.grid.col_label_size * zoom)

        for col, tab in self.code_array.col_widths:
            if tab == self.grid.current_table and \
               col < self.grid.code_array.shape[1]:
                zoomed_col_size = self.code_array.col_widths[(col, tab)] * zoom
                self.grid.SetColSize(col, zoomed_col_size)

    def _zoom_labels(self, zoom):
        """Adjust grid label font to zoom factor"""

        labelfont = self.grid.GetLabelFont()
        default_fontsize = get_default_font().GetPointSize()
        labelfont.SetPointSize(max(1, int(round(default_fontsize * zoom))))
        self.grid.SetLabelFont(labelfont)

    def zoom(self, zoom=None):
        """Zooms to zoom factor"""

        status = True

        if zoom is None:
            zoom = self.grid.grid_renderer.zoom
            status = False

        # Zoom factor for grid content
        self.grid.grid_renderer.zoom = zoom

        # Zoom grid labels
        self._zoom_labels(zoom)

        # Zoom rows and columns
        self._zoom_rows(zoom)
        self._zoom_cols(zoom)

        if self.main_window.IsFullScreen():
            # Do not display labels in fullscreen mode
            self.main_window.handlers.row_label_size = \
                self.grid.GetRowLabelSize()
            self.main_window.handlers.col_label_size = \
                self.grid.GetColLabelSize()

            self.grid.HideRowLabels()
            self.grid.HideColLabels()

        self.grid.ForceRefresh()

        if status:
            statustext = _(u"Zoomed to {0:.2f}.").format(zoom)

            post_command_event(self.main_window, self.StatusBarMsg,
                               text=statustext)

    def zoom_in(self):
        """Zooms in by zoom factor"""

        zoom = self.grid.grid_renderer.zoom

        target_zoom = zoom * (1 + config["zoom_factor"])

        if target_zoom < config["maximum_zoom"]:
            self.zoom(target_zoom)

    def zoom_out(self):
        """Zooms out by zoom factor"""

        zoom = self.grid.grid_renderer.zoom

        target_zoom = zoom * (1 - config["zoom_factor"])

        if target_zoom > config["minimum_zoom"]:
            self.zoom(target_zoom)

    def _get_rows_height(self):
        """Returns the total height of all grid rows"""

        tab = self.grid.current_table
        no_rows = self.grid.code_array.shape[0]
        default_row_height = self.grid.code_array.cell_attributes.\
            default_cell_attributes["row-height"]

        non_standard_row_heights = []
        __row_heights = self.grid.code_array.row_heights
        for __row, __tab in __row_heights:
            if __tab == tab:
                non_standard_row_heights.append(__row_heights[(__row, __tab)])

        rows_height = sum(non_standard_row_heights)
        rows_height += \
            (no_rows - len(non_standard_row_heights)) * default_row_height

        return rows_height

    def _get_cols_width(self):
        """Returns the total width of all grid cols"""

        tab = self.grid.current_table
        no_cols = self.grid.code_array.shape[1]
        default_col_width = self.grid.code_array.cell_attributes.\
            default_cell_attributes["column-width"]

        non_standard_col_widths = []
        __col_widths = self.grid.code_array.col_widths
        for __col, __tab in __col_widths:
            if __tab == tab:
                non_standard_col_widths.append(__col_widths[(__col, __tab)])

        cols_width = sum(non_standard_col_widths)
        cols_width += \
            (no_cols - len(non_standard_col_widths)) * default_col_width

        return cols_width

    def zoom_fit(self):
        """Zooms the rid to fit the window.

        Only has an effect if the resulting zoom level is between
        minimum and maximum zoom level.

        """

        zoom = self.grid.grid_renderer.zoom

        grid_width, grid_height = self.grid.GetSize()

        rows_height = self._get_rows_height() + \
            (float(self.grid.GetColLabelSize()) / zoom)
        cols_width = self._get_cols_width() + \
            (float(self.grid.GetRowLabelSize()) / zoom)

        # Check target zoom for rows
        zoom_height = float(grid_height) / rows_height

        # Check target zoom for columns
        zoom_width = float(grid_width) / cols_width

        # Use the minimum target zoom from rows and column target zooms
        target_zoom = min(zoom_height, zoom_width)

        # Zoom only if between min and max

        if config["minimum_zoom"] < target_zoom < config["maximum_zoom"]:
            self.zoom(target_zoom)

    # Tooltip actions

    def on_mouse_over(self, key):
        """Displays cell code of cell key in status bar"""

        def split_lines(string, line_length=80):
            """Returns string that is split into lines of length line_length"""

            result = u""
            line = 0

            while len(string) > line_length * line:
                line_start = line * line_length
                result += string[line_start:line_start+line_length]
                result += '\n'
                line += 1

            return result[:-1]

        row, col, tab = key

        # If the cell is a button cell or a frozen cell then do nothing
        cell_attributes = self.grid.code_array.cell_attributes
        if cell_attributes[key]["button_cell"] or \
           cell_attributes[key]["frozen"]:
            return

        if (row, col) != self.prev_rowcol and row >= 0 and col >= 0:
            self.prev_rowcol[:] = [row, col]

            max_result_length = int(config["max_result_length"])
            table = self.grid.GetTable()
            hinttext = table.GetSource(row, col, tab)[:max_result_length]

            if hinttext is None:
                hinttext = ''

            post_command_event(self.main_window, self.StatusBarMsg,
                               text=hinttext)

            cell_res = self.grid.code_array[row, col, tab]

            if cell_res is None:
                self.grid.SetToolTip(None)
                return

            try:
                cell_res_str = unicode(cell_res)
            except UnicodeEncodeError:
                cell_res_str = unicode(cell_res, encoding='utf-8')

            if len(cell_res_str) > max_result_length:
                cell_res_str = cell_res_str[:max_result_length] + ' [...]'

            self.grid.SetToolTipString(split_lines(cell_res_str))

    def get_visible_area(self):
        """Returns visible area

        Format is a tuple of the top left tuple and the lower right tuple

        """

        grid = self.grid

        top = grid.YToRow(grid.GetViewStart()[1] * grid.ScrollLineX)
        left = grid.XToCol(grid.GetViewStart()[0] * grid.ScrollLineY)

        # Now start at top left for determining the bottom right visible cell

        bottom, right = top, left

        while grid.IsVisible(bottom, left, wholeCellVisible=False):
            bottom += 1

        while grid.IsVisible(top, right, wholeCellVisible=False):
            right += 1

        # The derived lower right cell is *NOT* visible

        bottom -= 1
        right -= 1

        return (top, left), (bottom, right)

    def switch_to_table(self, event):
        """Switches grid to table

        Parameters
        ----------

        event.newtable: Integer
        \tTable that the grid is switched to

        """

        newtable = event.newtable

        no_tabs = self.grid.code_array.shape[2] - 1

        if 0 <= newtable <= no_tabs:
            self.grid.current_table = newtable

            self.grid.SetToolTip(None)

            # Delete renderer cache
            self.grid.grid_renderer.cell_cache.clear()

            # Delete video cells
            video_cells = self.grid.grid_renderer.video_cells
            for key in video_cells:
                video_panel = video_cells[key]
                video_panel.player.stop()
                video_panel.player.release()
                video_panel.Destroy()
            video_cells.clear()

            # Hide cell editor
            cell_editor = self.grid.GetCellEditor(self.grid.GetGridCursorRow(),
                                                  self.grid.GetGridCursorCol())

            try:
                cell_editor.Reset()
            except AttributeError:
                # No cell editor open
                pass

            self.grid.HideCellEditControl()

            # Change value of entry_line and table choice
            post_command_event(self.main_window, self.TableChangedMsg,
                               table=newtable)

            # Reset row heights and column widths by zooming

            self.zoom()

    def get_cursor(self):
        """Returns current grid cursor cell (row, col, tab)"""

        return self.grid.GetGridCursorRow(), self.grid.GetGridCursorCol(), \
            self.grid.current_table

    def set_cursor(self, value):
        """Changes the grid cursor cell.

        Parameters
        ----------

        value: 2-tuple or 3-tuple of String
        \trow, col, tab or row, col for target cursor position

        """

        shape = self.grid.code_array.shape

        if len(value) == 3:
            self.grid._last_selected_cell = row, col, tab = value
            if row < 0 or col < 0 or tab < 0 or \
               row >= shape[0] or col >= shape[1] or tab >= shape[2]:
                raise ValueError("Cell {value} outside of {shape}".format(
                                 value=value, shape=shape))

            if tab != self.cursor[2]:
                post_command_event(self.main_window,
                                   self.GridActionTableSwitchMsg, newtable=tab)
                if is_gtk():
                    try:
                        wx.Yield()
                    except:
                        pass
        else:
            row, col = value
            if row < 0 or col < 0 or row >= shape[0] or col >= shape[1]:
                raise ValueError("Cell {value} outside of {shape}".format(
                                 value=value, shape=shape))

            self.grid._last_selected_cell = row, col, self.grid.current_table

        if not (row is None and col is None):
            self.grid.MakeCellVisible(row, col)
            self.grid.SetGridCursor(row, col)

    cursor = property(get_cursor, set_cursor)


class SelectionActions(Actions):
    """Actions that affect the grid selection"""

    def get_selection(self):
        """Returns selected cells in grid as Selection object"""

        # GetSelectedCells: individual cells selected by ctrl-clicking
        # GetSelectedRows: rows selected by clicking on the labels
        # GetSelectedCols: cols selected by clicking on the labels
        # GetSelectionBlockTopLeft
        # GetSelectionBlockBottomRight: For blocks selected by dragging
        # across the grid cells.

        block_top_left = self.grid.GetSelectionBlockTopLeft()
        block_bottom_right = self.grid.GetSelectionBlockBottomRight()
        rows = self.grid.GetSelectedRows()
        cols = self.grid.GetSelectedCols()
        cells = self.grid.GetSelectedCells()

        return Selection(block_top_left, block_bottom_right, rows, cols, cells)

    def select_cell(self, row, col, add_to_selected=False):
        """Selects a single cell"""

        self.grid.SelectBlock(row, col, row, col,
                              addToSelected=add_to_selected)

    def select_slice(self, row_slc, col_slc, add_to_selected=False):
        """Selects a slice of cells

        Parameters
        ----------
         * row_slc: Integer or Slice
        \tRows to be selected
         * col_slc: Integer or Slice
        \tColumns to be selected
         * add_to_selected: Bool, defaults to False
        \tOld selections are cleared if False

        """

        if not add_to_selected:
            self.grid.ClearSelection()

        if row_slc == row_slc == slice(None, None, None):
            # The whole grid is selected
            self.grid.SelectAll()

        elif row_slc.stop is None and col_slc.stop is None:
            # A block is selected:
            self.grid.SelectBlock(row_slc.start, col_slc.start,
                                  row_slc.stop - 1, col_slc.stop - 1)
        else:
            for row in xrange(row_slc.start, row_slc.stop, row_slc.step):
                for col in xrange(col_slc.start, col_slc.stop, col_slc.step):
                    self.select_cell(row, col, add_to_selected=True)

    def delete_selection(self, selection=None, mark_unredo=True):
        """Deletes selection, marks content as changed

        If selection is None then the current grid selection is used.

        Parameters
        ----------

        selection: Selection, defaults to None
        \tSelection that shall be deleted
        mark_unredo: Boolean, defaults to True
        \tIf True deletion is marked as separate undo step

        """

        # Mark content as changed
        post_command_event(self.main_window, self.ContentChangedMsg,
                           changed=True)

        if selection is None:
            selection = self.get_selection()

        current_table = self.grid.current_table

        for row, col, tab in self.grid.code_array.dict_grid.keys():
            if tab == current_table and (row, col) in selection:
                self.grid.actions.delete_cell((row, col, tab),
                                              mark_unredo=False)

        if mark_unredo:
            self.grid.code_array.unredo.mark()

        self.grid.code_array.result_cache.clear()

    def delete(self):
        """Deletes a selection if any else deletes the cursor cell

        Refreshes grid after deletion

        """

        if self.grid.IsSelection():
            # Delete selection
            self.grid.actions.delete_selection()

        else:
            # Delete cell at cursor
            cursor = self.grid.actions.cursor
            self.grid.actions.delete_cell(cursor)

        # Update grid
        self.grid.ForceRefresh()

    def quote_selection(self):
        """Quotes selected cells, marks content as changed"""

        selection = self.get_selection()
        current_table = self.grid.current_table
        for row, col, tab in self.grid.code_array.dict_grid.keys():
            if tab == current_table and (row, col) in selection:
                self.grid.actions.quote_code((row, col, tab),
                                             mark_unredo=False)

        self.grid.code_array.unredo.mark()

        self.grid.code_array.result_cache.clear()

    def copy_selection_access_string(self):
        """Copys access_string to selection to the clipboard

        An access string is Python code to reference the selection
        If there is no selection then a reference to the current cell is copied

        """

        selection = self.get_selection()
        if not selection:
            cursor = self.grid.actions.cursor
            selection = Selection([], [], [], [], [tuple(cursor[:2])])
        shape = self.grid.code_array.shape
        tab = self.grid.current_table

        access_string = selection.get_access_string(shape, tab)

        # Copy access string to clipboard
        self.grid.main_window.clipboard.set_clipboard(access_string)

        # Display copy operation and access string in status bar
        statustext = _("Cell reference copied to clipboard: {access_string}")
        statustext = statustext.format(access_string=access_string)

        post_command_event(self.main_window, self.StatusBarMsg,
                           text=statustext)

    def _shifted_merge_area(self, merge_area, rows, cols):
        """Shifts merge area by rows and cols"""

        top, left, bottom, right = merge_area
        return top + rows, left + cols, bottom + rows, right + cols

    def copy_format(self):
        """Copies the format of the selected cells to the Clipboard

        Cells are shifted so that the top left bbox corner is at 0,0

        """

        row, col, tab = self.grid.actions.cursor
        code_array = self.grid.code_array

        # Cell attributes

        new_cell_attributes = []
        selection = self.get_selection()
        if not selection:
            # Current cell is chosen for selection
            selection = Selection([], [], [], [], [(row, col)])

        # Format content is shifted so that the top left corner is 0,0
        ((top, left), (bottom, right)) = \
            selection.get_grid_bbox(self.grid.code_array.shape)

        cell_attributes = code_array.cell_attributes
        for __selection, table, attrs in cell_attributes:
            if tab == table:
                new_selection = selection & __selection
                new_shifted_selection = new_selection.shifted(-top, -left)
                if "merge_area" in attrs and attrs["merge_area"]:
                    attrs["merge_area"] = \
                        self._shifted_merge_area(attrs["merge_area"],
                                                 -top, -left)
                new_cell_attributes.append(
                    (new_shifted_selection.parameters, table, attrs))

        # Rows

        shifted_new_row_heights = {}
        for row, table in code_array.row_heights:
            if tab == table and top <= row <= bottom:
                shifted_new_row_heights[row-top, table] = \
                    code_array.row_heights[row, table]

        # Columns

        shifted_new_col_widths = {}
        for col, table in code_array.col_widths:
            if tab == table and left <= col <= right:
                shifted_new_col_widths[col-left, table] = \
                    code_array.col_widths[col, table]

        format_data = {
            "cell_attributes": new_cell_attributes,
            "row_heights": shifted_new_row_heights,
            "col_widths": shifted_new_col_widths,
        }

        attr_string = repr(format_data)

        self.grid.main_window.clipboard.set_clipboard(attr_string)

    def paste_format(self):
        """Pastes cell formats

        Pasting starts at cursor or at top left bbox corner

        """

        row, col, tab = self.grid.actions.cursor

        selection = self.get_selection()
        if selection:
            # Use selection rather than cursor for top left cell if present
            row, col = [tl if tl is not None else 0
                        for tl in selection.get_bbox()[0]]

        cell_attributes = self.grid.code_array.cell_attributes

        string_data = self.grid.main_window.clipboard.get_clipboard()
        format_data = ast.literal_eval(string_data)

        ca = format_data["cell_attributes"]
        rh = format_data["row_heights"]
        cw = format_data["col_widths"]

        assert isinstance(ca, types.ListType)
        assert isinstance(rh, types.DictType)
        assert isinstance(cw, types.DictType)

        # Cell attributes

        for ca_ele in ca:
            base_selection = Selection(*ca_ele[0])
            shifted_selection = base_selection.shifted(row, col)
            attrs = ca_ele[2]
            if "merge_area" in attrs and attrs["merge_area"]:
                attrs["merge_area"] = \
                    self._shifted_merge_area(attrs["merge_area"], row, col)

            new_cell_attribute = shifted_selection, tab, attrs
            cell_attributes.undoable_append(new_cell_attribute)

        # Row heights
        row_heights = self.grid.code_array.row_heights
        for __row, __tab in rh:
            row_heights[__row+row, tab] = rh[__row, __tab]

        # Column widths
        col_widths = self.grid.code_array.col_widths
        for __col, __tab in cw:
            col_widths[__col+col, tab] = cw[(__col, __tab)]


class FindActions(Actions):
    """Actions for finding inside the grid"""

    def find_all(self, find_string, flags):
        """Return list of all positions of event_find_string in MainGrid.

        Only the code is searched. The result is not searched here.

        Parameters:
        -----------
        gridpos: 3-tuple of Integer
        \tPosition at which the search starts
        find_string: String
        \tString to find in grid
        flags: List of strings
        \t Search flag out of
        \t ["UP" xor "DOWN", "WHOLE_WORD", "MATCH_CASE", "REG_EXP"]

        """

        code_array = self.grid.code_array
        string_match = code_array.string_match

        find_keys = []

        for key in code_array:
            if string_match(code_array(key), find_string, flags) is not None:
                find_keys.append(key)

        return find_keys

    def find(self, gridpos, find_string, flags, search_result=True):
        """Return next position of event_find_string in MainGrid

        Parameters:
        -----------
        gridpos: 3-tuple of Integer
        \tPosition at which the search starts
        find_string: String
        \tString to find in grid
        flags: List of strings
        \tSearch flag out of
        \t["UP" xor "DOWN", "WHOLE_WORD", "MATCH_CASE", "REG_EXP"]
        search_result: Bool, defaults to True
        \tIf True then the search includes the result string (slower)

        """

        findfunc = self.grid.code_array.findnextmatch

        if "DOWN" in flags:
            if gridpos[0] < self.grid.code_array.shape[0]:
                gridpos[0] += 1
            elif gridpos[1] < self.grid.code_array.shape[1]:
                gridpos[1] += 1
            elif gridpos[2] < self.grid.code_array.shape[2]:
                gridpos[2] += 1
            else:
                gridpos = (0, 0, 0)
        elif "UP" in flags:
            if gridpos[0] > 0:
                gridpos[0] -= 1
            elif gridpos[1] > 0:
                gridpos[1] -= 1
            elif gridpos[2] > 0:
                gridpos[2] -= 1
            else:
                gridpos = [dim - 1 for dim in self.grid.code_array.shape]

        return findfunc(tuple(gridpos), find_string, flags, search_result)

    def replace_all(self, findpositions, find_string, replace_string):
        """Replaces occurrences of find_string with replace_string at findpos

        and marks content as changed

        Parameters
        ----------

        findpositions: List of 3-Tuple of Integer
        \tPositions in grid that shall be replaced
        find_string: String
        \tString to be overwritten in the cell
        replace_string: String
        \tString to be used for replacement

        """
        # Mark content as changed
        post_command_event(self.main_window, self.ContentChangedMsg,
                           changed=True)

        for findpos in findpositions:
            old_code = self.grid.code_array(findpos)
            new_code = old_code.replace(find_string, replace_string)

            self.grid.code_array[findpos] = new_code

        statustext = _("Replaced {no_cells} cells.")
        statustext = statustext.format(no_cells=len(findpositions))

        post_command_event(self.main_window, self.StatusBarMsg,
                           text=statustext)

        self.grid.ForceRefresh()

    def replace(self, findpos, find_string, replace_string):
        """Replaces occurrences of find_string with replace_string at findpos

        and marks content as changed

        Parameters
        ----------

        findpos: 3-Tuple of Integer
        \tPosition in grid that shall be replaced
        find_string: String
        \tString to be overwritten in the cell
        replace_string: String
        \tString to be used for replacement

        """

        # Mark content as changed
        post_command_event(self.main_window, self.ContentChangedMsg,
                           changed=True)

        old_code = self.grid.code_array(findpos)
        new_code = old_code.replace(find_string, replace_string)

        self.grid.code_array[findpos] = new_code
        self.grid.actions.cursor = findpos

        statustext = _("Replaced {old} with {new} in cell {key}.")
        statustext = statustext.format(old=old_code, new=new_code, key=findpos)

        post_command_event(self.main_window, self.StatusBarMsg,
                           text=statustext)


class AllGridActions(FileActions, TableActions, UnRedoActions,
                     GridActions, SelectionActions, FindActions, CellActions):
    """All grid actions as a bundle"""

    def __init__(self, grid):
        FileActions.__init__(self, grid)
        TableActions.__init__(self, grid)
        UnRedoActions.__init__(self, grid)
        GridActions.__init__(self, grid)
        SelectionActions.__init__(self, grid)
        FindActions.__init__(self, grid)
        CellActions.__init__(self, grid)

    def _replace_bbox_none(self, bbox):
        """Returns bbox, in which None is replaced by grid boundaries"""

        (bb_top, bb_left), (bb_bottom, bb_right) = bbox

        if bb_top is None:
            bb_top = 0

        if bb_left is None:
            bb_left = 0

        if bb_bottom is None:
            bb_bottom = self.code_array.shape[0] - 1

        if bb_right is None:
            bb_right = self.code_array.shape[1] - 1

        return (bb_top, bb_left), (bb_bottom, bb_right)
