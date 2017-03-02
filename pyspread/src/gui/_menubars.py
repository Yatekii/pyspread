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
_menubars
===========

Provides menubars

Provides:
---------
  1. ContextMenu: Context menu for main grid
  2. MainMenu: Main menu of pyspread

"""

import wx

from _events import post_command_event, EventMixin

import src.lib.i18n as i18n

# Use ugettext instead of getttext to avoid unicode errors
_ = i18n.language.ugettext


class _filledMenu(wx.Menu):
    """Menu that fills from the attribute menudata.

    Parameters:
    parent: object
    \tThe parent object that hosts the event handler methods
    menubar: wx.Menubar, defaults to parent
    \tThe menubar to which the menu is attached

    menudata has the following structure:
    [
        [wx.Menu, _("Menuname"), [
            [wx.MenuItem, ["Methodname"), _("Itemlabel"), _("Help")]] ,
            ...
            "Separator",
            ...
            [wx.Menu, ...],
            ...
        ],
    ...
    ]

    """

    menudata = []

    def __init__(self, *args, **kwargs):
        self.parent = kwargs.pop('parent')
        try:
            self.menubar = kwargs.pop('menubar')
        except KeyError:
            self.menubar = self.parent
        wx.Menu.__init__(self, *args, **kwargs)

        # id - message type storage
        self.ids_msgs = {}

        # Stores approve_item for disabling
        self.approve_item = None

        self._add_submenu(self, self.menudata)

    def _add_submenu(self, parent, data):
        """Adds items in data as a submenu to parent"""

        for item in data:
            obj = item[0]
            if obj == wx.Menu:
                try:
                    __, menuname, submenu, menu_id = item
                except ValueError:
                    __, menuname, submenu = item
                    menu_id = -1

                menu = obj()
                self._add_submenu(menu, submenu)

                if parent == self:
                    self.menubar.Append(menu, menuname)
                else:
                    parent.AppendMenu(menu_id, menuname, menu)

            elif obj == wx.MenuItem:
                try:
                    msgtype, shortcut, helptext, item_id = item[1]
                except ValueError:
                    msgtype, shortcut, helptext = item[1]
                    item_id = wx.NewId()

                try:
                    style = item[2]
                except IndexError:
                    style = wx.ITEM_NORMAL

                menuitem = obj(parent, item_id, shortcut, helptext, style)

                parent.AppendItem(menuitem)

                if _("&Approve file") == shortcut:
                    self.approve_item = menuitem

                self.ids_msgs[item_id] = msgtype

                self.parent.Bind(wx.EVT_MENU, self.OnMenu, id=item_id)

            elif obj == "Separator":
                parent.AppendSeparator()

            else:
                raise TypeError(_("Menu item unknown"))

    def OnMenu(self, event):
        """Menu event handler"""

        msgtype = self.ids_msgs[event.GetId()]
        post_command_event(self.parent, msgtype)

# end of class _filledMenu


class ContextMenu(_filledMenu, EventMixin):
    """Context menu for grid operations"""

    def __init__(self, *args, **kwargs):

        item = wx.MenuItem

        self.menudata = [
            [item, [self.CutMsg, _("Cu&t"), _("Cut cell to clipboard"),
                    wx.ID_CUT]],
            [item, [self.CopyMsg, _("&Copy"),
                    _("Copy input strings to clipboard"), wx.ID_COPY]],
            [item, [self.PasteMsg, _("&Paste"),
                    _("Paste cells from clipboard"), wx.ID_PASTE]],
            [item, [self.InsertRowsMsg, _("Insert &rows"),
                    _("Insert rows at cursor")]],
            [item, [self.InsertColsMsg, _("&Insert columns"),
                    _("Insert columns at cursor")]],
            [item, [self.DeleteRowsMsg, _("Delete rows"), _("Delete rows")]],
            [item, [self.DeleteColsMsg, _("Delete columns"),
                    _("Delete columns")]],
        ]

        _filledMenu.__init__(self, *args, **kwargs)

# end of class ContextMenu


class MainMenu(_filledMenu, EventMixin):
    """Main application menu"""

    def __init__(self, *args, **kwargs):

        item = wx.MenuItem

        self.menudata = [
            [wx.Menu, _("&File"), [
                [item, [self.NewMsg, _("&New") + "\tCtrl+n",
                        _("Create a new, empty spreadsheet"), wx.ID_NEW]],
                [item, [self.OpenMsg, _("&Open") + "\tCtrl+o",
                        _("Open spreadsheet from file"), wx.ID_OPEN]],
                ["Separator"],
                [item, [self.SaveMsg, _("&Save") + "\tCtrl+s",
                        _("Save spreadsheet"), wx.ID_SAVE]],
                [item, [self.SaveAsMsg, _("Save &As") + "\tShift+Ctrl+s",
                        _("Save spreadsheet to a new file")]],
                ["Separator"],
                [item, [self.ImportMsg, _("&Import"),
                        _("Import a file and paste it into current grid")]],
                [item, [self.ExportMsg, _("&Export"), _("Export selection to "
                        "file (Supported formats: CSV)")]],
                ["Separator"],
                [item, [self.ApproveMsg, _("&Approve file"),
                        _("Approve, unfreeze and sign the current file")]],
                ["Separator"],
                [item, [self.ClearGobalsMsg, _("&Clear globals"),
                        _("Deletes global variables from memory and reloads "
                          "base modules"), wx.ID_CLEAR]],
                ["Separator"],
                [item, [self.PageSetupMsg, _("Page setup"),
                        _("Setup printer page"), wx.ID_PAGE_SETUP]],
                [item, [self.PrintPreviewMsg, _("Print preview") +
                        "\tShift+Ctrl+p", _("Print preview"), wx.ID_PREVIEW]],
                [item, [self.PrintMsg, _("&Print") + "\tCtrl+p",
                        _("Print current spreadsheet"), wx.ID_PRINT]],
                ["Separator"],
                [item, [self.PreferencesMsg, _("Preferences..."),
                        _("Change preferences of pyspread"),
                        wx.ID_PREFERENCES]],
                [item, [self.NewGpgKeyMsg, _("Switch GPG key..."),
                        _("Create or choose a GPG key pair for signing and "
                          "verifying pyspread files")]],
                ["Separator"],
                [item, [self.CloseMsg, _("&Quit") + "\tCtrl+q",
                        _("Quit pyspread"), wx.ID_EXIT]]]],
            [wx.Menu, _("&Edit"), [
                [item, [self.UndoMsg, _("&Undo") + "\tCtrl+z",
                        _("Undo last step"), wx.ID_UNDO]],
                [item, [self.RedoMsg, _("&Redo") + "\tShift+Ctrl+z",
                        _("Redo last undone step"), wx.ID_REDO]],
                ["Separator"],
                [item, [self.CutMsg, _("Cu&t") + "\tCtrl+x",
                        _("Cut cell to clipboard"), wx.ID_CUT]],
                [item, [self.CopyMsg, _("&Copy") + "\tCtrl+c",
                        _("Copy the input strings of the cells to clipboard"),
                        wx.ID_COPY]],
                [item, [self.CopyResultMsg,
                        _("Copy &results") + "\tShift+Ctrl+c",
                        _("Copy the result strings of the cells to the "
                          "clipboard")]],
                [item, [self.PasteMsg, _("&Paste") + "\tCtrl+v",
                        _("Paste cells from clipboard"), wx.ID_PASTE]],
                [item, [self.PasteAsMsg, _("Paste &As...") + "\tShift+Ctrl+v",
                        _("Transform clipboard and paste cells into grid")]],
                [item, [self.SelectAll, _("Select A&ll") + "\tCtrl+A",
                        _("Select All Cells")]],
                ["Separator"],
                [item, [self.FindFocusMsg, _("&Find") + "\tCtrl+f",
                        _("Find cell by content"), wx.ID_FIND]],
                [item, [self.ReplaceMsg, _("Replace...") + "\tCtrl+Shift+f",
                        _("Replace strings in cells"), wx.ID_REPLACE]],
                ["Separator"],
                [item, [self.QuoteMsg, _("Quote cell(s)") + "\tCtrl+Enter",
                        _('Converts cell content to strings by adding quotes '
                          '("). If a selection is present then its cells are '
                          'quoted.')]],
                ["Separator"],
                [item, [self.SortAscendingMsg, _("Sort &ascending"),
                        _("Sort rows in selection or current table ascending "
                          "corresponding to row at cursor.")]],
                [item, [self.SortDescendingMsg, _("Sort &descending"),
                        _("Sort rows in selection or current table descending "
                          "corresponding to row at cursor.")]],
                ["Separator"],
                [item, [self.InsertRowsMsg, _("Insert &rows"),
                        _("Insert rows at cursor")]],
                [item, [self.InsertColsMsg, _("&Insert columns"),
                        _("Insert columns at cursor")]],
                [item, [self.InsertTabsMsg, _("Insert &table"),
                        _("Insert table before current table")]],
                ["Separator"],
                [item, [self.DeleteRowsMsg, _("Delete rows"),
                        _("Delete rows")]],
                [item, [self.DeleteColsMsg, _("Delete columns"),
                        _("Delete columns")]],
                [item, [self.DeleteTabsMsg, _("Delete table"),
                        _("Delete current table")]],
                ["Separator"],
                [item, [self.ShowResizeGridDialogMsg, _("Resize grid"),
                        _("Resize grid")]]]],
            [wx.Menu, _("&View"), [
                [item, [self.FullScreenMsg, _("Fullscreen") + "\tF11",
                        _("Shows grid in fullscreen mode. "
                          "Press <F11> to leave.")]],
                ["Separator"],
                [wx.Menu, _("Toolbars"), [
                    [item, [self.MainToolbarToggleMsg, _("Main toolbar"),
                            _("Shows and hides the main toolbar.")],
                        wx.ITEM_CHECK],
                    [item, [self.MacroToolbarToggleMsg, _("Macro toolbar"),
                            _("Shows and hides the macro toolbar.")],
                        wx.ITEM_CHECK],
                    [item, [self.WidgetToolbarToggleMsg, _("Widget toolbar"),
                            _("Shows and hides the widget toolbar.")],
                        wx.ITEM_CHECK],
                    [item, [self.AttributesToolbarToggleMsg,
                            _("Format toolbar"),
                            _("Shows and hides the format toolbar.")],
                        wx.ITEM_CHECK],
                    [item, [self.FindToolbarToggleMsg, _("Find toolbar"),
                            _("Shows and hides the find toolbar.")],
                        wx.ITEM_CHECK]]],
                [item, [self.EntryLineToggleMsg, _("Entry line"),
                        _("Shows and hides the entry line.")], wx.ITEM_CHECK],
                [item, [self.TableListToggleMsg, _("Table list"),
                        _("Shows and hides the table selection list.")],
                    wx.ITEM_CHECK],
                ["Separator"],
                [item, [self.DisplayGotoCellDialogMsg,
                        _("Go to cell") + "\tCtrl+G",
                        _("Moves the grid to a cell."), wx.ID_INDEX]],
                ["Separator"],
                [item, [self.SpellCheckMsg, _("Check spelling"),
                        _("Turn spell checking on and off.")], wx.ITEM_CHECK],
                ["Separator"],
                [item, [self.ZoomInMsg, _("Zoom in") + "\tCtrl++",
                        _("Zoom in grid."), wx.ID_ZOOM_IN]],
                [item, [self.ZoomOutMsg, _("Zoom out") + "\tCtrl+-",
                        _("Zoom out grid."), wx.ID_ZOOM_OUT]],
                [item, [self.ZoomStandardMsg, _("Normal size") + "\tCtrl+0",
                        _("Show grid in standard zoom."), wx.ID_ZOOM_100]],
                [item, [self.ZoomFitMsg, _("Zoom to fit") + "\tF6",
                        _("Zooms the grid to fit the visible window space."),
                        wx.ID_ZOOM_FIT]],
                ["Separator"],
                [item, [self.RefreshSelectionMsg,
                        _("Refresh selected cells") + "\tF5",
                        _("Refresh selected cells even when frozen"),
                        wx.ID_REFRESH]],
                [item, [self.TimerToggleMsg,
                        _("Toggle periodic updates"),
                        _("Toggles periodic cell updates for frozen cells")],
                 wx.ITEM_CHECK],
                ["Separator"],
                [item, [self.ViewFrozenMsg, _("Show Frozen"),
                        _("Shows which cells are currently frozen in a "
                          "crosshatch.")],
                 wx.ITEM_CHECK]]],
            [wx.Menu, _("F&ormat"), [
                [item, [self.CopyFormatMsg, _("Copy format") + "\tAlt+Ctrl+C",
                        _("Copy format of selection to the clipboard")]],
                [item, [self.PasteFormatMsg, _("Paste format") + "\tAlt+Ctrl+V",
                        _("Paste format of selection to the clipboard")]],
                ["Separator"],
                [item, [self.FontDialogMsg, _("Font..."),
                        _("Launch font dialog.")]],
                [item, [self.FontBoldMsg, _("Bold") + "\tCtrl+B",
                        _("Toggles bold."), wx.ID_BOLD]],
                [item, [self.FontItalicsMsg, _("Italics") + "\tCtrl+I",
                        _("Toggles italics."), wx.ID_ITALIC]],
                [item, [self.FontUnderlineMsg, _("Underline") + "\tCtrl+U",
                        _("Toggles underline."), wx.ID_UNDERLINE]],
                [item, [self.FontStrikethroughMsg, _("Strikethrough"),
                        _("Toggles strikethrough.")]],
                ["Separator"],
                [item, [self.TextColorDialogMsg, _("Text color..."),
                        _("Launch color dialog to specify text color.")]],
                [item, [self.BgColorDialogMsg, _("Background color..."),
                        _("Launch color dialog to specify background "
                          "color.")]],
                ["Separator"],
                [item, [self.MarkupMsg, _("Markup"),
                        _("Show cell result as Pango markup")]],
                ["Separator"],
                [wx.Menu, _("Justification"), [
                    [item, [self.JustificationMsg, _("Left"), _("Left"),
                            wx.ID_JUSTIFY_LEFT]],
                    [item, [self.JustificationMsg, _("Center"), _("Center"),
                            wx.ID_JUSTIFY_CENTER]],
                    [item, [self.JustificationMsg, _("Right"), _("Right"),
                            wx.ID_JUSTIFY_RIGHT]],
                ]],
                [wx.Menu, _("Alignment"), [
                    [item, [self.AlignmentMsg, alignment, alignment]]
                    for alignment in [_("Top"), _("Center"), _("Bottom")]]],
                [wx.Menu, _("Rotation"), [
                    [item, [self.Rotation0Msg,
                            _("0°"), _("Set text rotation to 0°")]],
                    [item, [self.Rotation90Msg,
                            _("90°"), _("Set text rotation to 90°")]],
                    [item, [self.Rotation180Msg,
                            _("180°"), _("Set text rotation to 180°")]],
                    [item, [self.Rotation270Msg,
                            _("270°"), _("Set text rotation to 270°")]],
                ]],
                ["Separator"],
                [item, [self.FrozenMsg, _("Frozen"),
                        _("Toggles frozen state of cell. ") +
                        _("Frozen cells are updated only "
                          "when F5 is pressed.")]],
                [item, [self.LockMsg, _("Lock"),
                        _("Lock cell. Locked cells cannot be changed.")]],
                [item, [self.MergeMsg, _("Merge cells"),
                        _("Merges / unmerges selected cells. ")]],
                ]],
            [wx.Menu, _("&Macro"), [
                [item, [self.MacroListMsg, _("&Macro list") + "\tCtrl+m",
                        _("Choose, fill in, manage, and create macros")]],
                [item, [self.MacroLoadMsg, _("&Load macro list"),
                        _("Load macro list")]],
                [item, [self.MacroSaveMsg, _("&Save macro list"),
                        _("Save macro list")]],
                ["Separator"],
                [item, [self.InsertBitmapMsg, _("Insert bitmap..."),
                        _("Insert bitmap from file into cell")]],
                [item, [self.LinkBitmapMsg, _("Link bitmap..."),
                        _("Link bitmap from file into cell")]],
                [item, [self.InsertChartMsg, _("Insert chart..."),
                        _("Insert chart into cell")]]]],
            [wx.Menu, _("&Help"), [
                [item, [self.ManualMsg, _("First &Steps"),
                        _("Launch First Steps in pyspread"), wx.ID_HELP]],
                [item, [self.TutorialMsg, _("&Tutorial"),
                        _("Launch tutorial")]],
                [item, [self.FaqMsg, _("&FAQ"),
                        _("Frequently asked questions")]],
                ["Separator"],
                [item, [self.DependenciesMsg, _("Dependencies"),
                        _("Overview of installed dependencies")]],
                ["Separator"],
                [item, [self.AboutMsg, _("&About"), _("About pyspread"),
                        wx.ID_ABOUT]]]]
        ]

        _filledMenu.__init__(self, *args, **kwargs)

    def enable_file_approve(self, enable=True):
        """Enables or disables menu item (for entering/leaving save mode)"""

        self.approve_item.Enable(enable)

# end of class MainMenu
