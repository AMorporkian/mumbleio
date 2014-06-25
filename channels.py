from logbook import debug, info, warning

from users import UserManager


__author__ = 'ankhmorporkian'


class ChannelManager:
    def __init__(self):
        debug("Creating channel manager.")
        self.channels = {}

    def add_channel(self, id, parent=None, name=None, links=None,
                    description=None, links_add=None, links_remove=None,
                    temporary=None, position=None, description_hash=None):
        debug("Creating channel {0}", id)
        if id in self.channels:
            self.update_channel(id, parent, name, links, description, links_add,
                                links_remove, temporary, position,
                                description_hash)
        channel = Channel(id, parent, name, links, description, links_add,
                          links_remove, temporary, position, description_hash)
        if parent is not None and parent != 0:
            if parent not in self.channels:
                raise KeyError("Got a child channel without a root channel (?)")
            self.channels[parent].children.add(channel)
        self.channels[id] = channel

    def del_channel(self, id):
        try:
            del self.channels[id]
            info("Deleted channel with ID {0}", id)
        except KeyError:
            warning("Server removed channel with ID {0}, "
                    "but we haven't seen it before!", id)

    def get_by_name(self, name):
        for id, channel in self.channels.items():
            if channel.name.lower() == name.lower():
                return channel
        raise KeyError("Couldn't find a channel with the name %s" % name)

    def get(self, id):
        if not isinstance(id, int):
            if not id.isdigit():
                id = self.get_by_name(id).id
            else:
                id = int(id)
        return self.channels[id]

    def update_channel(self,
                       *args):  # id, parent, name, links, description, links_add,
        #links_remove, temporary, position, description_hash):
        pass

    def add_from_message(self, message):
        args = []
        for m in (
                'channel_id', 'parent', 'name', 'links', 'description',
                'links_add',
                'links_remove', 'temporary', 'position', 'description_hash'):
            args.append(getattr(message, m, None))
        self.add_channel(*args)


class Channel:
    def __init__(self, id, parent, name, links, description, links_add,
                 links_remove, temporary, position, description_hash):
        self.id = id
        self.name = name
        self.position = position
        self.parent = parent
        self.links = links
        self.description = description
        self.links_add = links_add
        self.links_remove = links_remove
        self.temporary = temporary
        self.description_hash = description_hash
        self.users = UserManager()
        self.children = set()