from __future__ import absolute_import, division, print_function

import unittest

from jobrunner.service import service


class SvcBase(object):
    @staticmethod
    def new():
        raise NotImplementedError

    def api(self, arg):
        raise NotImplementedError


class Svc1(SvcBase):
    @staticmethod
    def new():
        return Svc1()

    def api(self, arg):
        return 'service1:{}'.format(arg)


class Svc2(SvcBase):
    @staticmethod
    def new():
        return Svc2()

    def api(self, arg):
        return 'service2:{}'.format(arg)


class ServiceTest(unittest.TestCase):
    def setUp(self):
        service().clear(thisIsATest=True)

    def testSingle(self):
        service().register('service', Svc1)
        svc = service().service.new()
        self.assertEqual('service1:foo', svc.api('foo'))
        self.assertEqual('service1:bar', svc.api('bar'))

    def testReRegister(self):
        service().register('service', Svc1)
        svc = service().service.new()
        self.assertEqual('service1:foo', svc.api('foo'))

    def testRegisterTwice(self):
        service().register('service', Svc1)
        service().register('service', Svc1)
        with self.assertRaises(AssertionError):
            service().register('service', Svc2)

    def testMultiple(self):
        service().register('s1', Svc1)
        service().register('s2', Svc2)
        svc1 = service().s1.new()
        svc2 = service().s2.new()
        self.assertEqual('service1:foo', svc1.api('foo'))
        self.assertEqual('service2:foo', svc2.api('foo'))
