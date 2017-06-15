from tkinter import *
from tkinter.ttk import *

from PIL import ImageTk, Image
from os.path import isfile

from utils import sanitize_string, get_display


class EntityCard(Frame):
    """Improved entry with support for validation, delete and paste.
       As optional arguments, it can take:
         field max_length = integer
         function on_change(entry_contents)
         function paste_filter(clipboard_contents) returns string
    """
    def __init__(self, master=None, **kwargs):

        # Set the custom attributes and pop'em out
        self.entity = kwargs.pop('entity')

        # Initialize the frame
        kwargs['borderwidth'] = 2
        kwargs['relief'] = 'ridge'
        super().__init__(master, **kwargs)

        # Set up our custom widget
        self.profile_picture = Label(self)
        self.profile_picture.grid(row=0, column=0, sticky=NSEW)

        self.right_column = Frame(self, padding=(16, 0))
        self.right_column.grid(row=0, column=1)

        self.name_label = Label(self.right_column,
                                   text=get_display(self.entity),
                                   font='-weight bold -size 14')
        self.name_label.grid(row=0, sticky=NW)

        if hasattr(self.entity, 'username'):
            self.username_label = Label(self.right_column,
                                           text='@{}'.format(self.entity.username),
                                           font='-size 12')
            self.username_label.grid(row=1, sticky=NW)

        if hasattr(self.entity, 'phone'):
            self.phone_label = Label(self.right_column,
                                        text='+{}'.format(self.entity.phone))
            self.phone_label.grid(row=2, sticky=NW)

        elif hasattr(self.entity, 'participants_count'):
            self.participants_label = Label(self.right_column,
                                               text='{} participants'.format(self.entity.participants_count))
            self.participants_label.grid(row=2, sticky=NW)

    def update_profile_photo(self, photo_file):
        """Updates the profile photo"""
        if photo_file and isfile(photo_file):
            self.profile_picture_photo = ImageTk.PhotoImage(
                Image.open(photo_file).resize((128, 128), Image.ANTIALIAS))

            self.profile_picture.config(image=self.profile_picture_photo)
