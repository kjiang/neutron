# Copyright 2014 Cisco Systems, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import netaddr
import testscenarios

from neutron.agent.common import ovs_lib
from neutron.agent.linux import bridge_lib
from neutron.agent.linux import ip_lib
from neutron.common import constants as n_const
from neutron.tests import base as tests_base
from neutron.tests.common import base as common_base
from neutron.tests.common import net_helpers
from neutron.tests.functional import base as functional_base


BR_PREFIX = 'test-br'
PORT_PREFIX = 'test-port'
MARK_VALUE = '0x1'
MARK_MASK = '0xffffffff'
ICMP_MARK_RULE = ('-j MARK --set-xmark %(value)s/%(mask)s'
                  % {'value': MARK_VALUE, 'mask': MARK_MASK})
MARKED_BLOCK_RULE = '-m mark --mark %s -j DROP' % MARK_VALUE
ICMP_BLOCK_RULE = '-p icmp -j DROP'


#TODO(jschwarz): Move these two functions to neutron/tests/common/
get_rand_name = tests_base.get_rand_name


def get_rand_bridge_name():
    return get_rand_name(prefix=BR_PREFIX,
                         max_length=n_const.DEVICE_NAME_MAX_LEN)


class BaseLinuxTestCase(functional_base.BaseSudoTestCase):

    def _create_namespace(self, prefix=net_helpers.NS_PREFIX):
        return self.useFixture(net_helpers.NamespaceFixture(prefix)).ip_wrapper

    def create_veth(self):
        return self.useFixture(net_helpers.VethFixture()).ports


# Regarding MRO, it goes BaseOVSLinuxTestCase, WithScenarios,
# BaseLinuxTestCase, ..., UnitTest, object. setUp is not dfined in
# WithScenarios, so it will correctly be found in BaseLinuxTestCase.
class BaseOVSLinuxTestCase(testscenarios.WithScenarios, BaseLinuxTestCase):
    scenarios = [
        ('vsctl', dict(ovsdb_interface='vsctl')),
        ('native', dict(ovsdb_interface='native')),
    ]

    def setUp(self):
        super(BaseOVSLinuxTestCase, self).setUp()
        self.config(group='OVS', ovsdb_interface=self.ovsdb_interface)
        self.ovs = ovs_lib.BaseOVS()
        self.ip = ip_lib.IPWrapper()

    def create_ovs_bridge(self, br_prefix=BR_PREFIX):
        br = common_base.create_resource(br_prefix, self.ovs.add_bridge)
        self.addCleanup(br.destroy)
        return br

    def create_ovs_port_in_ns(self, br, ns):
        def create_port(name):
            br.replace_port(name, ('type', 'internal'))
            self.addCleanup(br.delete_port, name)
            return name
        port_name = common_base.create_resource(PORT_PREFIX, create_port)
        port_dev = self.ip.device(port_name)
        ns.add_device_to_namespace(port_dev)
        port_dev.link.set_up()
        return port_dev

    def bind_namespace_to_cidr(self, namespace, br, ip_cidr):
        """Bind namespace to cidr (on layer2 and 3).

        Bind the namespace to a subnet by creating an ovs port in the namespace
        and configuring port ip.
        """
        net = netaddr.IPNetwork(ip_cidr)
        port_dev = self.create_ovs_port_in_ns(br, namespace)
        port_dev.addr.add(str(net))
        return port_dev


class BaseIPVethTestCase(BaseLinuxTestCase):
    SRC_ADDRESS = '192.168.0.1'
    DST_ADDRESS = '192.168.0.2'

    @staticmethod
    def _set_ip_up(device, cidr):
        device.addr.add(cidr)
        device.link.set_up()

    def prepare_veth_pairs(self, src_ns_prefix=net_helpers.NS_PREFIX,
                           dst_ns_prefix=net_helpers.NS_PREFIX):

        src_addr = self.SRC_ADDRESS
        dst_addr = self.DST_ADDRESS

        src_veth, dst_veth = self.create_veth()
        src_ns = self._create_namespace(src_ns_prefix)
        dst_ns = self._create_namespace(dst_ns_prefix)
        src_ns.add_device_to_namespace(src_veth)
        dst_ns.add_device_to_namespace(dst_veth)

        self._set_ip_up(src_veth, '%s/24' % src_addr)
        self._set_ip_up(dst_veth, '%s/24' % dst_addr)

        return src_ns, dst_ns


class BaseBridgeTestCase(BaseIPVethTestCase):

    def create_veth_pairs(self, dst_namespace):
        src_ns = self._create_namespace()
        dst_ns = ip_lib.IPWrapper(dst_namespace)

        src_veth, dst_veth = self.create_veth()
        src_ns.add_device_to_namespace(src_veth)
        dst_ns.add_device_to_namespace(dst_veth)

        return src_veth, dst_veth

    def create_bridge(self, br_ns=None):
        br_ns = br_ns or self._create_namespace()
        br_name = get_rand_bridge_name()
        bridge = bridge_lib.BridgeDevice.addbr(br_name, br_ns.namespace)
        self.addCleanup(bridge.delbr)
        bridge.link.set_up()
        self.addCleanup(bridge.link.set_down)
        return bridge
