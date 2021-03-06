#   Copyright (c) 2016 Regents of The University of Michigan.
#   All Rights Reserved.
#
#   Permission to use, copy, modify, and distribute this software and
#   its documentation for any purpose and without fee is hereby granted,
#   provided that the above copyright notice appears in all copies and
#   that both that copyright notice and this permission notice appear
#   in supporting documentation, and that the name of The University
#   of Michigan not be used in advertising or publicity pertaining to
#   distribution of the software without specific, written prior
#   permission. This software is supplied as is without expressed or
#   implied warranties of any kind.

import os
import sys
import time
import datetime
import json

sys.path.append('../')
from splunklib import modularinput as smi

'''
    Only edit validate_input and stream_events
    Do not edit any other part in this file!!!
'''
class MyScript(smi.Script):

    def __init__(self):
        super(MyScript, self).__init__()
        self._canceled = False

    def load_checkpoint( self, ew, chk_dir, log):
        chk_file = os.path.join(chk_dir, log)
        try:
            file = open(chk_file)
            chktime = file.read().strip()
            file.close()
            message = "Loaded last timestamp of %s from %s checkpoint" % (
                    time.ctime(float(chktime)), chk_file )
            ew.log('INFO', message)
        except IOError:
            chktime = 0

        return int(chktime)

    def save_checkpoint(self, ew, chk_dir, log, time):
        chk_file = os.path.join(chk_dir, log)
        try:
            file = open(chk_file, 'w')
            file.write(time)
            file.close()
        except IOError:
            message = "Couldn't write checkpoint file %s" % ( chk_file )
            ew.log('FATAL', message)
            raise e

    def get_logs(self, inputs, ew, admin, log):
        checkpoint_dir = inputs.metadata.get("checkpoint_dir")
        lasttime = self.load_checkpoint(ew, checkpoint_dir, log)
        if not lasttime:
            ew.log( 'INFO', "no checkpoint time returned, using history value" )
            lasttime = int(time.time()) - (int(self.input_items['history']) * 86400)
        message = "Using checkpoint time %d" % (lasttime)
        ew.log('INFO', message)
        try:
            events = getattr(admin, log)(lasttime + 1)
        except RuntimeError as e:
            if "429" in e.message:
                ew.log( 'ERROR', "Received 429, too many requests. You may need to increase interval")
            return

        message = "%s retrieved %d events from host %s" % (log, len(events), self.input_items['api_host'])
        ew.log( "INFO", message )

        times = []
        for e in events:
            etype = e.pop('eventtype')
            st = ":".join(["duo", etype])
            timestamp = e.pop('timestamp')
            times.append(timestamp)
            apihost = e.pop('host')
            event = smi.Event(
                data = json.dumps(e),
                time = timestamp,
                host = apihost,
                index = self.output_index,
                sourcetype = st)
            try:
                ew.write_event(event)
            except Exception as e:
                raise e

        if len(times) > 0:
            self.save_checkpoint(ew, checkpoint_dir, log, str(max(times)))

    def get_summary(self, ew, admin):
        ew.log( 'INFO', "getting info summary" )
        response = admin.get_info_summary()
        event = smi.Event(
                data = json.dumps(response),
                host = admin.host,
                index = self.output_index,
                sourcetype = "duo:info_summary")
        try:
            ew.write_event(event)
        except Exception as e:
            raise e

    # GET SCHEME BEGIN
    def get_scheme(self):
        """overloaded splunklib modularinput method"""
        scheme = smi.Scheme("duo")
        scheme.title = ("DUO Security 2fa logs")
        scheme.description = ("Input for DUO security 2fa activity logs from Admin logging api")
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False

        scheme.add_argument(smi.Argument("name", title="Name",
                                         description="",
                                         required_on_create=True))
        scheme.add_argument(smi.Argument("get_telephony_log", title="Telephony Log",
                                         description="DUO Security Telephony Activity Log",
                                         data_type=smi.Argument.data_type_boolean,
                                         required_on_create=True,
                                         required_on_edit=True))
        scheme.add_argument(smi.Argument("get_authentication_log", title="Authentication Log",
                                         description="DUO Security Authentication Activity Log",
                                         data_type=smi.Argument.data_type_boolean,
                                         required_on_create=True,
                                         required_on_edit=True))
        scheme.add_argument(smi.Argument("get_administrator_log", title="Administration Log",
                                         description="DUO Security Administration Activity Log",
                                         data_type=smi.Argument.data_type_boolean,
                                         required_on_create=True,
                                         required_on_edit=True))
        scheme.add_argument(smi.Argument("get_summary", title="Info Summary",
                                         description="DUO Security Account Info",
                                         data_type=smi.Argument.data_type_boolean,
                                         required_on_create=True,
                                         required_on_edit=True))
        scheme.add_argument(smi.Argument("history", title="Historical Data",
                                         description="Days of historical data on initial input",
                                         data_type=smi.Argument.data_type_number,
                                         required_on_create=True,
                                         required_on_edit=False))
        scheme.add_argument(smi.Argument("api_host", title="API Hostname",
                                         description="DUO Admin API hostname",
                                         required_on_create=True,
                                         required_on_edit=True))
        scheme.add_argument(smi.Argument("skey", title="Secret Key",
                                         description="DUO Admin API Secret Key",
                                         required_on_create=True,
                                         required_on_edit=True))
        scheme.add_argument(smi.Argument("ikey", title="Integration Key",
                                         description="DUO Admin API Integration Key",
                                         required_on_create=True,
                                         required_on_edit=True))
        return scheme
    # GET SCHEME END

    def validate_input(self, definition):
        """overloaded splunklib modularinput method"""
        import requests
        import duo_client

        interval = definition.parameters.get("interval")
        host = definition.parameters.get("api_host")
        url = "https://" + host + "/auth/v2/ping"
        try:
            response = requests.get(url)
        except Exception as e:
            raise e

        if response.status_code != 200:
            raise ValueError('GET request to API host failed')

        try:
            s = response.json()["stat"]
            if s != "OK":
                raise ValueError("Didn't receive OK from duo api host")
        except Exception as e:
            raise e

        """
        api_auth = duo_client.Auth(
            ikey = definition.parameters.get('ikey'),
            skey = definition.parameters.get('skey'),
            host = definition.parameters.get['api_host'],
            ca_certs = None)
        try:
            response = api_auth.check()
        except Exception as e:
            raise e

        if response.status_code != 200:
            raise ValueError("Duo auth check failed")
        """

    def stream_events(self, inputs, ew):
        """overloaded splunklib modularinput method"""
        # get input options
        self.input_name, self.input_items = inputs.inputs.popitem()
        self.output_index = self.input_items['index']
        #self.output_sourcetype = self.input_items['sourcetype']

        # get options from setup page
        # from TA_DUOSecurity2FA_setup_util import Setup_Util
        # uri = self._input_definition.metadata["server_uri"]
        # session_key = self._input_definition.metadata['session_key']
        # setup_util = Setup_Util(uri, session_key)
        # log_level = setup_util.get_log_level()
        # proxy_settings = setup_util.get_proxy_settings()
        # account = setup_util.get_credential_account("admin")
        # userdefined = setup_util.get_customized_setting("userdefined")

        import duo_client

        api_admin = duo_client.Admin(
            ikey = self.input_items['ikey'],
            skey = self.input_items['skey'],
            host = self.input_items['api_host'],
            ca_certs = None)

        if self.input_items['get_authentication_log'] in ['1', 'true', 'enabled',]:
            self.get_logs(inputs, ew, api_admin, "get_authentication_log")
        else: ew.log('INFO', "get_authentication_log not enabled")
        if self.input_items['get_telephony_log'] in ['1', 'true', 'enabled',]:
            self.get_logs(inputs, ew, api_admin, "get_telephony_log")
        else: ew.log('INFO', "get_telephony_log not enabled")
        if self.input_items['get_administrator_log'] in ['1', 'true', 'enabled',]:
            self.get_logs(inputs, ew, api_admin, "get_administrator_log")
        else: ew.log('INFO', "get_administrator_log not enabled")
        if self.input_items['get_summary'] in ['1','true','enabled',]:
            self.get_summary(ew, api_admin)
        else: ew.log('INFO', "get_summary not enabled")


if __name__ == "__main__":
    exitcode = MyScript().run(sys.argv)
    sys.exit(exitcode)
