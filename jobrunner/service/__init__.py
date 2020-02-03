from __future__ import absolute_import, division, print_function


class _Registry(object):
    def __init__(self):
        self._services = {}

    def register(self, identifier, obj):
        if '.' not in identifier:
            assert (identifier not in self._services
                    or self._services[identifier] == obj)
            self._services[identifier] = obj
        else:
            scope, key = identifier.split('.', 1)
            if scope not in self._services:
                self._services[scope] = _Registry()
            self._services[scope].register(key, obj)

    def clear(self, thisIsATest=False):
        assert thisIsATest
        self._services.clear()

    def __getattr__(self, key):
        if key not in self._services:
            raise AttributeError
        return self._services[key]


__REGISTRY = _Registry()


def service():
    return __REGISTRY
