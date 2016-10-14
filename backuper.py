import json
from time import sleep
from datetime import timedelta
from os import makedirs, path

from telethon import RPCError
from telethon.utils import get_display_name, get_extension
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

from tl_database import TLDatabase

# Load the current scheme layer
import telethon.tl.all_tlobjects as all_tlobjects
scheme_layer = all_tlobjects.layer
del all_tlobjects


class Backuper:

    # region Initialize

    def __init__(self, client, peer_id,
                 download_delay=1,
                 download_chunk_size=100,
                 backups_dir='backups'):
        """
        :param client:              An initialized TelegramClient, which will be used to download the messages
        :param peer_id:             The ID of the peer for the backup
        :param download_delay:      The download delay, in seconds, after a message chunk is downloaded
        :param download_chunk_size: The chunk size (i.e. how many messages do we download every time)
                                    The maximum allowed by Telegram is 100
        :param backups_dir:         Where the backups will be stored
        """
        self.client = client
        self.download_delay = download_delay
        self.download_chunk_size = download_chunk_size
        self.backups_dir = path.join(backups_dir, str(peer_id))

        # Ensure the directory for the backups
        makedirs(self.backups_dir, exist_ok=True)

        self.db = None  # This will be loaded later

    # endregion

    @staticmethod
    def get_peer_id(peer):
        """Gets the peer ID for a given peer (which can be an user, a chat or a channel)
           If the peer is neither of these, no error will be rose"""
        peer_id = getattr(peer, 'user_id', None)
        if not peer_id:
            peer_id = getattr(peer, 'chat_id', None)
            if not peer_id:
                peer_id = getattr(peer, 'channel_id', None)

        return peer_id

    def save_metadata(self, peer, peer_name, resume_msg_id):
        """Saves the metadata for the current peer"""
        with open(path.join(self.backups_dir, 'metadata'), 'w') as file:
            json.dump({
                'peer_id': self.get_peer_id(peer),
                'peer_name': peer_name,
                'peer_constructor': peer.constructor_id,
                'resume_msg_id': resume_msg_id,
                'scheme_layer': scheme_layer
            }, file)

    def load_metadata(self):
        """Loads the metadata of the current peer"""
        file_path = path.join(self.backups_dir, 'metadata')
        if not path.isfile(file_path):
            return None
        else:
            with open(file_path, 'r') as file:
                return json.load(file)

    def get_create_media_dirs(self):
        """Retrieves the paths for the profile photos, photos,
           documents and stickers backups directories, creating them too"""
        directories = []
        for directory in ('profile_photos', 'photos', 'documents', 'stickers'):
            current = path.join(self.backups_dir, 'media', directory)
            makedirs(current, exist_ok=True)
            directories.append(current)

        return directories

    # region Making backups

    def begin_backup(self, input_peer, peer_name):
        """Begins the backup on the given peer"""

        # Create a connection to the database
        db_file = path.join(self.backups_dir, 'backup.sqlite')
        self.db = TLDatabase(db_file)

        # Load the previous data
        # We need to know the latest message ID so we can resume the backup
        metadata = self.load_metadata()
        if metadata:
            last_id = metadata.get('resume_msg_id')
            # Do not check for the scheme layers to be the same,
            # the database is meant to be consistent always
        else:
            last_id = 0

        # Determine whether we started making the backup from the very first message or not.
        # If this is the case:
        #   We won't need to come back to the first message again after we've finished downloading
        #   them all, since that first message will already be in backup.
        #
        # Otherwise, if we did not start from the first message:
        #   More messages were in the backup already, and after we backup those "left" ones,
        #   we must return to the first message and backup until where we started.
        started_at_0 = last_id == 0

        # Keep an internal downloaded count for it to be faster
        downloaded_count = self.db.count('messages')

        # Make the backup
        try:
            while True:
                result = self.client.invoke(GetHistoryRequest(
                    peer=input_peer,
                    offset_id=last_id,
                    limit=self.download_chunk_size,
                    offset_date=None,
                    add_offset=0,
                    max_id=0,
                    min_id=0
                ))
                total_messages = getattr(result, 'count', len(result.messages))

                # First add users and chats, replacing any previous value
                for user in result.users:
                    self.db.add_object(user, replace=True)
                for chat in result.chats:
                    self.db.add_object(chat, replace=True)

                # Then add the messages to the backup
                for msg in result.messages:
                    if self.db.in_table(msg.id, 'messages'):
                        # If the message we retrieved was already saved, this means that we're
                        # done because we have the rest of the messages!
                        # Clear the list so we enter the next if, and break to early terminate
                        last_id = result.messages[-1].id
                        del result.messages[:]
                        break
                    else:
                        self.db.add_object(msg)
                        downloaded_count += 1
                        last_id = msg.id

                # Always commit at the end to save changes
                self.db.commit()
                self.save_metadata(peer=input_peer, peer_name=peer_name, resume_msg_id=last_id)

                if result.messages:
                    # We downloaded and added more messages, so print progress
                    print('[{:.2%}, ETA: {}] Downloaded {} out of {} messages'.format(
                        downloaded_count / total_messages,
                        self.calculate_eta(downloaded_count, total_messages),
                        downloaded_count,
                        total_messages))
                else:
                    # We've downloaded all the messages since the last backup
                    if started_at_0:
                        # And since we started from the very first message, we have them all
                        print('Downloaded all {}'.format(total_messages))
                        break
                    else:
                        # We need to start from the first message (latest sent message)
                        # and backup again until we have them all
                        last_id = 0
                        started_at_0 = True

                # Always sleep a bit, or Telegram will get angry and tell us to chill
                sleep(self.download_delay)

            pass  # end while

        except KeyboardInterrupt:
            print('Operation cancelled, not downloading more messages!')
            # Also commit here, we don't want to lose any information!
            self.db.commit()
            self.save_metadata(peer=input_peer, peer_name=peer_name, resume_msg_id=last_id)

    def begin_backup_media(self, db_file, dl_propics, dl_photos, dl_documents):
        propics_dir, photos_dir, documents_dir, stickers_dir = \
            self.get_create_media_dirs()

        db = TLDatabase(db_file)

        # TODO Spaghetti code, refactor
        if dl_propics:
            total = db.count('users where photo not null')
            print("Starting download for {} users' profile photos..".format(total))
            for i, user in enumerate(db.query_users('where photo not null')):
                output = path.join(propics_dir, '{}{}'
                                   .format(user.photo.photo_id, get_extension(user.photo)))

                # Try downloading the photo
                try:
                    if path.isfile(output):
                        ok = True
                    else:
                        ok = self.client.download_profile_photo(user.photo,
                                                                add_extension=False,
                                                                file_path=output)
                except RPCError:
                    ok = False

                # Show the corresponding message
                if ok:
                    print('Downloaded {} out of {}, now for profile photo for "{}"'
                          .format(i, total, get_display_name(user)))
                else:
                    print('Downloaded {} out of {}, could not download profile photo for "{}"'
                          .format(i, total, get_display_name(user)))

        if dl_photos:
            total = db.count('messages where media_id = {}'.format(MessageMediaPhoto.constructor_id))
            print("Starting download for {} photos...".format(total))
            for i, msg in enumerate(db.query_messages('where media_id = {}'.format(MessageMediaPhoto.constructor_id))):
                output = path.join(photos_dir, '{}{}'
                                   .format(msg.media.photo.id, get_extension(msg.media)))

                # Try downloading the photo
                try:
                    if path.isfile(output):
                        ok = True
                    else:
                        ok = self.client.download_msg_media(msg.media,
                                                            add_extension=False,
                                                            file_path=output)
                except RPCError:
                    ok = False

                # Show the corresponding message
                if ok:
                    print('Downloaded {} out of {} photos'.format(i, total))
                else:
                    print('Photo {} out of {} download failed'.format(i, total))

        if dl_documents:
            total = db.count('messages where media_id = {}'.format(MessageMediaDocument.constructor_id))
            print("Starting download for {} documents...".format(total))
            for i, msg in enumerate(db.query_messages('where media_id = {}'.format(MessageMediaDocument.constructor_id))):
                output = path.join(documents_dir, '{}{}'
                                   .format(msg.media.document.id, get_extension(msg.media)))

                # Try downloading the document
                try:
                    if path.isfile(output):
                        ok = True
                    else:
                        ok = self.client.download_msg_media(msg.media,
                                                            add_extension=False,
                                                            file_path=output)
                except RPCError:
                    ok = False

                # Show the corresponding message
                if ok:
                    print('Downloaded {} out of {} documents'.format(i, total))
                else:
                    print('Document {} out of {} download failed'.format(i, total))

    # endregion

    def calculate_eta(self, downloaded, total):
        """Calculates the Estimated Time of Arrival (ETA)"""
        left = total - downloaded
        chunks_left = (left + self.download_chunk_size - 1) // self.download_chunk_size
        eta = chunks_left * self.download_delay
        return timedelta(seconds=eta)
