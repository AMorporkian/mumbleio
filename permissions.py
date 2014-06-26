import asyncio
import itertools

from logbook import debug, warning, exception


__author__ = 'ankhmorporkian'


class Permission:
    def __init__(self, name, subpermissions=None):
        self.name = name
        z = set()

        def get_permissions(p):
            nonlocal z
            z.add(p)
            if p.subpermissions:
                for r in p.subpermissions:
                    z.add(r)
                    get_permissions(r)
            return z

        self.subpermissions = set()
        if subpermissions:
            print(subpermissions)
            self.subpermissions = set()
            for x in subpermissions:
                self.subpermissions |= get_permissions(x)







class Restrict:
    def __init__(self, permission):
        """
        If there are decorator arguments, the function
        to be decorated is not passed to the constructor!
        """
        self.perm = permission

    def __call__(self, f):
        debug("In __call__")
        if not asyncio.iscoroutine(f):
            f = asyncio.coroutine(f)

        @asyncio.coroutine
        def wrapped_f(s, source, *args, **kwargs):
            print(self.perm.name, source.permissions, self.perm.name in source.permissions)
            if self.perm.name in source.permissions:
                try:
                    return (yield from f(s, source, *args, **kwargs))
                except (IndexError, KeyError, ValueError) as e:
                    exception("Unhandled exception in permission wrapper. "
                              "Silently dropping.")
            else:
                raise PermissionError(self.perm)
        wrapped_f.__doc__ = f.__doc__
        return wrapped_f


everyone = Permission("everyone")
grouper = Permission("grouper", subpermissions=(everyone,))
admin = Permission("admin", subpermissions=(grouper,))
owner = Permission("owner", subpermissions=(admin,))




all_perms = {x.name: x for x in [owner, admin, grouper]}
