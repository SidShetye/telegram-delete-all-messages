import os
import json
from datetime import datetime, timedelta, timezone

from time import sleep

from pyrogram import Client
from pyrogram.raw.functions.messages import Search
from pyrogram.raw.types import InputPeerSelf, InputMessagesFilterEmpty
from pyrogram.raw.types.messages import ChannelMessages
from pyrogram.errors import FloodWait, UnknownError

cachePath = os.path.abspath(__file__)
cachePath = os.path.dirname(cachePath)
cachePath = os.path.join(cachePath, "cache")

if os.path.exists(cachePath):
    with open(cachePath, "r") as cacheFile:
        cache = json.loads(cacheFile.read())
    
    API_ID = cache["API_ID"]
    API_HASH = cache["API_HASH"]
else:
    API_ID = os.getenv('API_ID', None) or int(input('Enter your Telegram API id: '))
    API_HASH = os.getenv('API_HASH', None) or input('Enter your Telegram API hash: ')

app = Client("client", api_id=API_ID, api_hash=API_HASH)

if not os.path.exists(cachePath):
    with open(cachePath, "w") as cacheFile:
        cache = {"API_ID": API_ID, "API_HASH": API_HASH}
        cacheFile.write(json.dumps(cache))


class Cleaner:
    def __init__(self, chats=None, search_chunk_size=100, delete_chunk_size=100, days_threshold=None):
        self.chats = chats or []
        if search_chunk_size > 100:
            # https://github.com/gurland/telegram-delete-all-messages/issues/31
            #
            # The issue is that pyrogram.raw.functions.messages.Search uses
            # pagination with chunks of 100 messages. Might consider switching
            # to search_messages, which handles pagination transparently.
            raise ValueError('search_chunk_size > 100 not supported')
        self.search_chunk_size = search_chunk_size
        self.delete_chunk_size = delete_chunk_size
        self.days_threshold = days_threshold
        self.cutoff_datetime = None
        if days_threshold:
            self.set_days_threshold(days_threshold)

    @staticmethod
    def chunks(l, n):
        """Yield successive n-sized chunks from l.
        https://stackoverflow.com/questions/312443/how-do-you-split-a-list-into-evenly-sized-chunks#answer-312464"""
        for i in range(0, len(l), n):
            yield l[i:i + n]

    @staticmethod
    async def get_all_chats():        
        async with app:
            dialogs = []
            async for dialog in app.get_dialogs():
                dialogs.append(dialog.chat)
            return dialogs

    async def select_groups(self, recursive=0):
        chats = await self.get_all_chats()
        groups = [c for c in chats if c.type.name in ('GROUP, SUPERGROUP')]

        print('Delete all your messages in')
        for i, group in enumerate(groups):
            print(f'  {i+1}. {group.title}')

        print(
            f'  {len(groups) + 1}. '
            '(!) DELETE ALL YOUR MESSAGES IN ALL OF THOSE GROUPS (!)\n'
        )

        nums_str = input('Insert option numbers (comma separated): ')
        nums = map(lambda s: int(s.strip()), nums_str.split(','))

        for n in nums:
            if not 1 <= n <= len(groups) + 1:
                print('Invalid option selected. Exiting...')
                exit(-1)

            if n == len(groups) + 1:
                print('\nTHIS WILL DELETE ALL YOUR MESSSAGES IN ALL GROUPS!')
                answer = input('Please type "I understand" to proceed: ')
                if answer.upper() != 'I UNDERSTAND':
                    print('Better safe than sorry. Aborting...')
                    exit(-1)
                self.chats = groups
                break
            else:
                self.chats.append(groups[n - 1])
        
        groups_str = ', '.join(c.title for c in self.chats)
        print(f'\nSelected {groups_str}.\n')

        if recursive == 1:
            self.run()

    def prompt_days_threshold(self):
        while True:
            try:
                days_input = input('Delete only messages older than how many days? ')
                days = int(days_input.strip())
                if days <= 0:
                    raise ValueError
            except ValueError:
                print('Please enter a positive integer value (e.g. 30).')
                continue

            self.set_days_threshold(days)
            print(f'\nMessages newer than {days} day(s) will be skipped.\n')
            break

    def set_days_threshold(self, days):
        if days <= 0:
            raise ValueError('days_threshold must be a positive integer')
        self.days_threshold = days
        now = datetime.now(timezone.utc)
        self.cutoff_datetime = now - timedelta(days=days)

    def filter_messages_by_age(self, messages):
        if not self.cutoff_datetime:
            return messages

        filtered_messages = []
        for message in messages:
            message_date = message.date
            if message_date.tzinfo is None:
                message_date = message_date.replace(tzinfo=timezone.utc)
            if message_date <= self.cutoff_datetime:
                filtered_messages.append(message)

        return filtered_messages

    async def run(self):
        if not self.cutoff_datetime:
            raise ValueError('Days threshold not set. Call prompt_days_threshold() before run().')

        for chat in self.chats:
            chat_id = chat.id
            message_ids = []
            add_offset = 0

            while True:
                q = await self.search_messages(chat_id, add_offset)
                filtered_messages = self.filter_messages_by_age(q)
                message_ids.extend(msg.id for msg in filtered_messages)
                messages_count = len(q)
                print(f'Found {len(message_ids)} of your messages in "{chat.title}"')
                if messages_count < self.search_chunk_size:
                    break
                add_offset += self.search_chunk_size

            await self.delete_messages(chat_id=chat.id, message_ids=message_ids)

    async def delete_messages(self, chat_id, message_ids):
        print(f'Deleting {len(message_ids)} messages with message IDs:')
        print(message_ids)
        for chunk in self.chunks(message_ids, self.delete_chunk_size):
            try:
                async with app:
                    await app.delete_messages(chat_id=chat_id, message_ids=chunk)
            except FloodWait as flood_exception:
                sleep(flood_exception.x)

    async def search_messages(self, chat_id, add_offset):
        async with app:
            messages = []
            print(f'Searching messages. OFFSET: {add_offset}')
            async for message in app.search_messages(
                chat_id=chat_id,
                offset=add_offset,
                from_user="me",
                limit=self.search_chunk_size,
            ):
                messages.append(message)
            return messages

async def main():
    try:
        deleter = Cleaner()
        await deleter.select_groups()
        deleter.prompt_days_threshold()
        await deleter.run()
    except UnknownError as e:
        print(f'UnknownError occured: {e}')
        print('Probably API has changed, ask developers to update this utility')

app.run(main())
