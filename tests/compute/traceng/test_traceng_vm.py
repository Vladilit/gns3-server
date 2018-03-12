# -*- coding: utf-8 -*-
#
# Copyright (C) 2018 GNS3 Technologies Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import pytest
import asyncio
import os
import sys

from tests.utils import asyncio_patch, AsyncioMagicMock
from gns3server.utils import parse_version
from unittest.mock import patch, MagicMock, ANY

from gns3server.compute.traceng.traceng_vm import TraceNGVM
from gns3server.compute.traceng.traceng_error import TraceNGError
from gns3server.compute.traceng import TraceNG
from gns3server.compute.notification_manager import NotificationManager


@pytest.fixture
def manager(port_manager):
    m = TraceNG.instance()
    m.port_manager = port_manager
    return m


@pytest.fixture(scope="function")
def vm(project, manager, ubridge_path):
    vm = TraceNGVM("test", "00010203-0405-0607-0809-0a0b0c0d0e0f", project, manager)
    vm._start_ubridge = AsyncioMagicMock()
    vm._ubridge_hypervisor = MagicMock()
    vm._ubridge_hypervisor.is_running.return_value = True
    return vm


def test_vm(project, manager):
    vm = TraceNGVM("test", "00010203-0405-0607-0809-0a0b0c0d0e0f", project, manager)
    assert vm.name == "test"
    assert vm.id == "00010203-0405-0607-0809-0a0b0c0d0e0f"


def test_vm_invalid_traceng_path(vm, manager, loop):
    with patch("gns3server.compute.traceng.traceng_vm.TraceNGVM._traceng_path", return_value="/tmp/fake/path/traceng"):
        with pytest.raises(TraceNGError):
            nio = manager.create_nio({"type": "nio_udp", "lport": 4242, "rport": 4243, "rhost": "127.0.0.1"})
            vm.port_add_nio_binding(0, nio)
            loop.run_until_complete(asyncio.async(vm.start()))
            assert vm.name == "test"
            assert vm.id == "00010203-0405-0607-0809-0a0b0c0d0e0e"


def test_start(loop, vm, async_run):
    process = MagicMock()
    process.returncode = None

    with NotificationManager.instance().queue() as queue:
        async_run(queue.get(0))  # Ping

        with asyncio_patch("gns3server.compute.traceng.traceng_vm.TraceNGVM._check_requirements", return_value=True):
            with asyncio_patch("asyncio.create_subprocess_exec", return_value=process) as mock_exec:
                with asyncio_patch("gns3server.compute.traceng.traceng_vm.TraceNGVM.start_wrap_console"):
                    loop.run_until_complete(asyncio.async(vm.start()))
                    assert mock_exec.call_args[0] == (vm._traceng_path(),
                                                      '-p',
                                                      str(vm._internal_console_port),
                                                      '-s',
                                                      ANY,
                                                      '-c',
                                                      ANY,
                                                      '-t',
                                                      '127.0.0.1')
                assert vm.is_running()
                assert vm.command_line == ' '.join(mock_exec.call_args[0])
        (action, event, kwargs) = async_run(queue.get(0))
        assert action == "node.updated"
        assert event == vm


def test_stop(loop, vm, async_run):
    process = MagicMock()

    # Wait process kill success
    future = asyncio.Future()
    future.set_result(True)
    process.wait.return_value = future
    process.returncode = None

    with NotificationManager.instance().queue() as queue:
        with asyncio_patch("gns3server.compute.traceng.traceng_vm.TraceNGVM._check_requirements", return_value=True):
            with asyncio_patch("gns3server.compute.traceng.traceng_vm.TraceNGVM.start_wrap_console"):
                with asyncio_patch("asyncio.create_subprocess_exec", return_value=process):
                    nio = TraceNG.instance().create_nio({"type": "nio_udp", "lport": 4242, "rport": 4243, "rhost": "127.0.0.1", "filters": {}})
                    async_run(vm.port_add_nio_binding(0, nio))

                    async_run(vm.start())
                    assert vm.is_running()

                    with asyncio_patch("gns3server.utils.asyncio.wait_for_process_termination"):
                        loop.run_until_complete(asyncio.async(vm.stop()))
                    assert vm.is_running() is False

                    if sys.platform.startswith("win"):
                        process.send_signal.assert_called_with(1)
                    else:
                        process.terminate.assert_called_with()

                    async_run(queue.get(0))  #  Ping
                    async_run(queue.get(0))  #  Started

                    (action, event, kwargs) = async_run(queue.get(0))
                    assert action == "node.updated"
                    assert event == vm


def test_reload(loop, vm, async_run):
    process = MagicMock()

    # Wait process kill success
    future = asyncio.Future()
    future.set_result(True)
    process.wait.return_value = future
    process.returncode = None

    with asyncio_patch("gns3server.compute.traceng.traceng_vm.TraceNGVM._check_requirements", return_value=True):
        with asyncio_patch("gns3server.compute.traceng.traceng_vm.TraceNGVM.start_wrap_console"):
            with asyncio_patch("asyncio.create_subprocess_exec", return_value=process):
                nio = TraceNG.instance().create_nio({"type": "nio_udp", "lport": 4242, "rport": 4243, "rhost": "127.0.0.1", "filters": {}})
                async_run(vm.port_add_nio_binding(0, nio))
                async_run(vm.start())
                assert vm.is_running()

                vm._ubridge_send = AsyncioMagicMock()
                with asyncio_patch("gns3server.utils.asyncio.wait_for_process_termination"):
                    async_run(vm.reload())
                assert vm.is_running() is True

                #if sys.platform.startswith("win"):
                #    process.send_signal.assert_called_with(1)
                #else:
                process.terminate.assert_called_with()


def test_add_nio_binding_udp(vm, async_run):
    nio = TraceNG.instance().create_nio({"type": "nio_udp", "lport": 4242, "rport": 4243, "rhost": "127.0.0.1", "filters": {}})
    async_run(vm.port_add_nio_binding(0, nio))
    assert nio.lport == 4242


def test_port_remove_nio_binding(vm):
    nio = TraceNG.instance().create_nio({"type": "nio_udp", "lport": 4242, "rport": 4243, "rhost": "127.0.0.1"})
    vm.port_add_nio_binding(0, nio)
    vm.port_remove_nio_binding(0)
    assert vm._ethernet_adapter.ports[0] is None


def test_close(vm, port_manager, loop):
    with asyncio_patch("gns3server.compute.traceng.traceng_vm.TraceNGVM._check_requirements", return_value=True):
        with asyncio_patch("asyncio.create_subprocess_exec", return_value=MagicMock()):
            vm.start()
            loop.run_until_complete(asyncio.async(vm.close()))
            assert vm.is_running() is False
