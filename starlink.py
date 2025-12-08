#!/usr/bin/env python

from gi.repository import GLib
import logging
import sys
import os
import platform
import dbus
import grpc
from hashlib import sha256

# Import generated gRPC stubs
import dishy_pb2
import dishy_pb2_grpc

# Make sure the path includes Victron libraries
sys.path.insert(1, '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python')
from vedbus import VeDbusService
from settingsdevice import SettingsDevice

VERSION = open("/data/dbus-starlink/version", "r").read().strip()

class Dishy:
    def __init__(self, target="192.168.100.1:9200"):
        self.channel = grpc.insecure_channel(target)
        self.stub = dishy_pb2_grpc.DeviceStub(self.channel)
        self.timeout = 10.0  # seconds
        
    def close(self):
        if self.channel:
            self.channel.close()

    def _make_request(self, **args):
        try:
            request = dishy_pb2.Request(**args)
            response = self.stub.Handle(request, timeout=self.timeout)
            if response.status.code != 0:
                logging.warning(f"Starlink request failed: {response.status.message} (code: {response.status.code})")
                return None
            return response
        except grpc.RpcError as e:
            logging.error(f"gRPC error during Starlink request: {e.code()}: {e.details()}")
            raise

    def get_device_info(self):
        r = self._make_request(get_device_info=dishy_pb2.GetDeviceInfoRequest())
        return r.get_device_info.device_info


    def get_position(self):
        r = self._make_request(get_location=dishy_pb2.GetLocationRequest())
        
        if r.status.code != 0:
            logging.warning(f"Starlink location request failed: {r.status.message} (code: {r.status.code})")
            return {"latitude": None, "longitude": None, "altitude": None}
            
        location = r.location
        return {
            "latitude": location.lla.lat if location.HasField('lla') else None,
            "longitude": location.lla.lon if location.HasField('lla') else None,
            "altitude": location.lla.alt if location.HasField('lla') else None
        }

class DbusService:
    def __init__(self, target="192.168.100.1:9200"):
        self.dishy = Dishy(target=target)
        info = self.dishy.get_device_info()
        self.id = sha256(info.id.encode()).hexdigest()[:8]

        logging.info(f"Starting driver for device {self.id}")

        self.servicename = f'com.victronenergy.gps.starlink_{self.id}'
        self._dbusservice = VeDbusService(self.servicename, register=False)

        # Create the management D-Bus entries
        self._dbusservice.add_path('/Management/ProcessName', 'dbus-starlink')
        self._dbusservice.add_path('/Management/ProcessVersion', VERSION)
        self._dbusservice.add_path('/Management/Connection', 'gRPC')

        # Create device-level D-Bus entries
        self._dbusservice.add_path('/DeviceInstance', 1)
        self._dbusservice.add_path('/ProductId', 45108)
        self._dbusservice.add_path('/ProductName', 'Starlink')
        self._dbusservice.add_path('/FirmwareVersion', info.software_version if info.HasField('software_version') else 'N/A')
        self._dbusservice.add_path('/HardwareVersion', info.hardware_version if info.HasField('hardware_version') else 'N/A')
        self._dbusservice.add_path('/Connected', 1)
        self._dbusservice.add_path('/Serial', info.id)
        self._dbusservice.add_path('/State', 0x100)

        # Create GPS specific paths
        self._dbusservice.add_path('/Fix', 0)  # No fix initially
        self._dbusservice.add_path('/Position/Latitude', 0.0)
        self._dbusservice.add_path('/Position/Longitude', 0.0)
        self._dbusservice.add_path('/Position/Altitude', 0.0)

        # ---- Persistent Settings ----
        self._settings = self._setup_settings()
        custom_name_key = 'CustomName'
        self._dbusservice.add_path(
            path='/CustomName',
            value=self._settings[custom_name_key],
            writeable=True,
            onchangecallback=lambda p, v, key=custom_name_key: self._handle_writable_setting_change(key, p, v)
        )

        self._dbusservice.register()
        self.refresh()

    def _setup_settings(self):
        settings_path_prefix = f'/Settings/Devices/starlink_{self.id}'
        supported_settings = {
            'CustomName': [f'{settings_path_prefix}/CustomName', f'Starlink', 0, 0]
        }
        return SettingsDevice(dbus.SystemBus(), supported_settings, None)

    def refresh(self):
        location = self.dishy.get_position()
        if location["latitude"] is not None and location["longitude"] is not None:
            self._dbusservice['/Fix'] = 1  # Fix acquired
            self._dbusservice['/Position/Latitude'] = location["latitude"]
            self._dbusservice['/Position/Longitude'] = location["longitude"]
            self._dbusservice['/Position/Altitude'] = int(location["altitude"])
            logging.info(f"Updated position: Lat {location['latitude']}, Lon {location['longitude']}, Alt {location['altitude']}")
        else:
            self._dbusservice['/Fix'] = 0  # No fix
            logging.info("No GPS fix available from Starlink.")
        
def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
    
    mainloop = GLib.MainLoop()

    service = DbusService()
    GLib.timeout_add(60000, service.refresh)

    logging.info(f"D-Bus service started. Entering main loop.")
    mainloop.run()

if __name__ == "__main__":
    main()
