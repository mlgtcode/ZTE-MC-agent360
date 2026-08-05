#!/usr/bin/env python
"""
ZTEROUTER AGENT360 custom plugin.

Configuration:
1) Copy this file to the agent360 plugins directory as ZTEROUTER.py.
2) Add this section to /etc/agent360-custom.ini:

[ZTEROUTER]
enabled = yes
ip = 192.168.1.1
password = your_router_password
# username is optional; some ZTE routers do not require it.
# username = admin

3) Test plugin:
     agent360 test ZTEROUTER

4) Restart agent to start reporting:
     service agent360 restart

Repository info:
- Source project: ZTE Router Integration for Home Assistant
- Repo: https://github.com/Kajkac/ZTE-MC-Home-assistant-repo
- Main base file: custom_components/zte_router/mc.py
- Scope: local polling for ZTE MC/G5 devices, exposing signal/connectivity and
    related router telemetry/services.
- License in upstream repo: GPL-3.0

Thank-you note:
Special thanks to Kajkac and contributors of the ZTE-MC-Home-assistant-repo for
the original router logic and ongoing maintenance. This AGENT360 plugin is
adapted from:
https://github.com/Kajkac/ZTE-MC-Home-assistant-repo/blob/main/custom_components/zte_router/mc.py
"""

import hashlib
import json
import logging
import ssl

import plugins
import urllib3

try:
    from http.cookies import SimpleCookie
except ImportError:
    from Cookie import SimpleCookie

try:
    from urllib.parse import urlencode, quote
except ImportError:
    from urllib import urlencode, quote


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)


ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE
try:
    ssl_context.set_ciphers("DEFAULT:@SECLEVEL=0")
except Exception:
    pass

s = urllib3.PoolManager(cert_reqs="CERT_NONE", ssl_context=ssl_context)


class zteRouter(object):
    def __init__(self, ip, username, password):
        self.ip = ip
        self.protocol = "http"
        self.username = username
        self.password = password
        self.cookies = {}
        self.stok = None
        self.uses_stok = False

        self.try_set_protocol()
        self.referer = "%s://%s/" % (self.protocol, self.ip)

    def authenticate(self):
        """Authenticate and store credentials (stok and AD) in instance fields."""
        LD = self.get_LD()
        AD = self.get_AD()
        stok = self.getCookie(self.username, self.password, LD, AD)
        self._zte_auth_stok = stok
        self._zte_auth_AD = AD
        self._zte_auth_LD = LD

    def request_with_session(self, method, url, headers=None, body=None):
        if headers is None:
            headers = {}
        if self.stok:
            headers["Cookie"] = "stok=%s" % self.stok

        response = s.request(method, url, headers=headers, body=body)
        if response.status in [502, 503, 504] or response.status >= 520:
            raise ConnectionError("Router unavailable (status %s)" % response.status)
        return response

    def try_set_protocol(self):
        protocols = ["https", "http"]
        for protocol in protocols:
            url = "%s://%s/index.html" % (protocol, self.ip)
            try:
                response = s.request("GET", url, timeout=2, retries=2)
                if response.status in [200, 301, 302]:
                    self.protocol = protocol
                    return
            except Exception:
                pass
        self.protocol = "http"

    def hash(self, value):
        # Router firmware requires this exact challenge-response hashing sequence.
        return hashlib.sha256(value.encode()).hexdigest()

    def getVersion(self):
        header = {"Referer": self.referer}
        payload = "isTest=false&cmd=wa_inner_version"
        url = self.referer + "goform/goform_get_cmd_process?" + payload
        try:
            r = self.request_with_session("GET", url, headers=header)
            data = r.data.decode("utf-8")
            return json.loads(data)["wa_inner_version"]
        except Exception:
            return ""

    def get_LD(self):
        header = {"Referer": self.referer}
        payload = "isTest=false&cmd=LD"
        url = self.referer + "goform/goform_get_cmd_process?" + payload
        try:
            r = self.request_with_session("GET", url, headers=header)
            data = r.data.decode("utf-8")
            return json.loads(data)["LD"].upper()
        except Exception:
            return ""

    def getCookie(self, username, password, LD, AD):
        # Keep authentication flow as-is.
        header = {"Referer": self.referer}

        hashPassword = self.hash(password).upper()
        ztePass = self.hash(hashPassword + LD).upper()

        if username:
            goform_id = "LOGIN_MULTI_USER"
            payload = {
                "isTest": "false",
                "goformId": goform_id,
                "user": username,
                "password": ztePass,
                "AD": AD,
            }
        else:
            goform_id = "LOGIN"
            payload = {
                "isTest": "false",
                "goformId": goform_id,
                "password": ztePass,
            }

        url = self.referer + "goform/goform_set_cmd_process"
        body = urlencode(payload).encode("utf-8")

        r = self.request_with_session("POST", url, headers=header, body=body)

        cookie = SimpleCookie()
        set_cookie_header = r.headers.get("Set-Cookie", "")
        if set_cookie_header:
            cookie.load(set_cookie_header)

        stok = cookie.get("stok")
        if stok:
            self.uses_stok = True
            self.stok = stok.value
        else:
            self.uses_stok = False
            self.stok = None

        self.cookies = {}
        for key, morsel in cookie.items():
            self.cookies[key] = morsel.value

        return self.stok

    def get_AD(self):
        # Keep AD calculation behavior as-is.
        def md5_fn(value):
            h = hashlib.md5()
            h.update(value.encode("utf-8"))
            return h.hexdigest()

        def sha256_fn(value):
            h = hashlib.sha256()
            h.update(value.encode("utf-8"))
            return h.hexdigest().upper()

        wa_inner_version = self.getVersion()
        if wa_inner_version == "":
            return ""

        is_mc888 = "MC888" in wa_inner_version
        is_mc889 = "MC889" in wa_inner_version
        hash_function = sha256_fn if is_mc888 or is_mc889 else md5_fn

        cr_version = ""
        a_value = hash_function(wa_inner_version + cr_version)

        header = {"Referer": self.referer}
        try:
            rd_url = self.referer + "goform/goform_get_cmd_process?isTest=false&cmd=RD"
            rd_response = self.request_with_session("GET", rd_url, headers=header)
            data = rd_response.data.decode("utf-8")
            rd_json = json.loads(data)
            u_value = rd_json.get("RD", "")
            return hash_function(a_value + u_value)
        except Exception:
            return ""

    def fetch_api_info(self):
        """Fetch broad read-only API info to report to AGENT360."""
        header = {
            "Host": self.ip,
            "Referer": "%sindex.html" % self.referer,
        }

        def has_value(value):
            if value is None:
                return False
            if isinstance(value, str):
                return value.strip() != ""
            return True

        # Pull a broad set of read-only keys in chunks to avoid query-size limits.
        param_groups = {
            "system_info": (
                "wa_inner_version,cr_version,loginfo,new_version_state,current_upgrade_state,"
                "is_mandatory,modem_main_state,pin_status,signalbar,imei,"
                "imsi,iccid,hardware_version,wa_version,sim_imsi,mac_address,web_version,LocalDomain"
            ),
            "radio_network": (
                "network_type,network_provider,network_provider_fullname,rmcc,rmnc,mdm_mcc,mdm_mnc,"
                "rssi,ecio,ecio_1,ecio_2,ecio_3,ecio_4,rscp,rscp_1,rscp_2,rscp_3,rscp_4,lte_rsrp,"
                "lte_rsrp_1,lte_rsrp_2,lte_rsrp_3,lte_rsrp_4,lte_rsrq,lte_snr,lte_snr_1,lte_snr_2,lte_snr_3,lte_snr_4,"
                "lte_rssi,Z5g_rsrp,Z5g_rsrq,Z5g_snr,Z5g_SINR,Z5g_dlEarfcn,Z5g_CELL_ID,ZCELLINFO_band,"
                "enodeb_id,lte_pci,lte_pci_lock,lte_band,lte_ca_pcell_band,lte_ca_scell_band,lte_ca_scell_info,"
                "lte_multi_ca_scell_info,lte_multi_ca_scell_sig_info,lte_ca_scell_arfcn,lte_ca_scell_bandwidth,"
                "lte_ca_pcell_bandwidth,lte_ca_pcell_arfcn,lte_ca_pcell_freq,lte_earfcn_lock,nr5g_action_band,"
                "nr5g_action_channel,nr5g_action_nsa_band,nr5g_pci,nr5g_cell_id,nr_ca_pcell_band,nr_ca_pcell_freq,"
                "nr5g_nsa_band_lock,nr5g_sa_band_lock,nr_multi_ca_scell_info,wan_active_band,wan_active_channel,"
                "cell_id,tx_power,ngbr_cell_info,5g_rx0_rsrp,5g_rx1_rsrp"
            ),
            "connectivity": (
                "wan_ipaddr,wan_apn,wan_connect_status,wan_lte_ca,opms_wan_mode,opms_wan_auto_mode,"
                "ppp_status,pppoe_status,dial_mode,dhcp_wan_status,static_wan_status,static_wan_ipaddr,"
                "ip_passthrough_enabled,vpn_conn_status,ppp_dial_conn_fail_counter"
            ),
            "ipv6_config": (
                "ipv6_wan_ipaddr,pdp_type,ipv6_pdp_type,pdp_type_ui,ipv6_pdp_type_ui"
            ),
            "wifi": (
                "wifi_enable,wifi_onoff_state,wifi_5g_enable,wifi_chip_temp,wifi_dfs_status,ssid,EX_SSID1,EX_wifi_profile,"
                "m_ssid_enable,m_SSID2,wifi_chip1_ssid1_ssid,wifi_chip2_ssid1_ssid,wifi_chip1_ssid1_auth_mode,"
                "wifi_chip2_ssid1_auth_mode,wifi_chip1_ssid2_access_sta_num,wifi_chip2_ssid2_access_sta_num,"
                "wifi_chip1_ssid1_access_sta_num,wifi_chip2_ssid1_access_sta_num,wifi_chip1_ssid2_max_access_num,"
                "wifi_chip2_ssid2_max_access_num,wifi_chip1_ssid1_wifi_coverage,wifi_access_sta_num,sta_ip_status,"
                "guest_switch"
            ),
            "wifi_advanced": (
                "wifi_chip1_ssid1_password_encode,wifi_chip2_ssid1_password_encode,wifi_chip1_ssid1_switch_onoff,"
                "wifi_chip2_ssid1_switch_onoff,wifi_chip1_ssid2_switch_onoff,wifi_chip2_ssid2_switch_onoff,"
                "wifi_chip1_ssid1_max_access_num,wifi_chip2_ssid1_max_access_num,wifi_chip2_ssid2_max_access_num,"
                "wifi_chip2_ssid2_ssid,wifi_chip1_ssid2_ssid,wifi_lbd_enable,m_HideSSID,station_ip_addr"
            ),
            "power_sensors": (
                "battery_value,battery_pers,battery_charging,battery_vol_percent,pm_modem_5g,pm_sensor_5g,"
                "pm_sensor_mdm,pm_sensor_ambient,pm_sensor_pa1"
            ),
            "usage_misc": (
                "monthly_rx_bytes,monthly_tx_bytes,monthly_time,realtime_rx_bytes,realtime_tx_bytes,"
                "realtime_rx_thrpt,realtime_tx_thrpt,realtime_time,date_month,data_volume_limit_switch,"
                "data_volume_limit_size,data_volume_alert_percent,data_volume_limit_unit,roam_setting_option,"
                "upg_roam_switch,privacy_read_flag,is_night_mode,check_web_conflict,station_mac,lan_ipaddr,"
                "sms_received_flag,sms_unread_num,sts_received_flag,spn_name_data,spn_b1_flag,spn_b2_flag,"
                "simcard_roam,"
                "flux_realtime_tx_bytes,flux_realtime_rx_bytes,flux_realtime_time,"
                "flux_realtime_tx_thrpt,flux_realtime_rx_thrpt,"
                "flux_monthly_rx_bytes,flux_monthly_tx_bytes,flux_monthly_time,"
                "flux_data_volume_limit_size,flux_data_volume_alert_percent,flux_data_volume_limit_unit"
            ),
            "dns_config": (
                "dns_mode,prefer_dns_manual,standby_dns_manual"
            ),
            "unclassified": (
                "RadioOff,apn_interface_version,bandwidth,network_information,Lte_ca_status"
            ),
        }

        grouped = {}
        add_params = {}
        fetch_errors = {}
        url_base = (
            self.referer
            + "goform/goform_get_cmd_process?isTest=false&multi_data=1&cmd="
        )
        known_keys = set()

        for group_name, param_str in param_groups.items():
            params = [p for p in param_str.split(",") if p]
            known_keys.update(params)
            chunks = [params[i:i + 60] for i in range(0, len(params), 60)]
            group_data = {}

            for idx, chunk in enumerate(chunks, start=1):
                cmd_encoded = quote(",".join(chunk), safe="")
                url = url_base + cmd_encoded

                try:
                    response = self.request_with_session("GET", url, headers=header)
                    payload = json.loads(response.data.decode("utf-8"))
                    if isinstance(payload, dict):
                        for key in chunk:
                            if key in payload and has_value(payload[key]):
                                group_data[key] = payload[key]
                        for key, value in payload.items():
                            if key not in known_keys and has_value(value):
                                add_params[key] = value
                    else:
                        fetch_errors["%s_chunk_%d" % (group_name, idx)] = "Non-dict payload"
                except Exception as exc:
                    fetch_errors["%s_chunk_%d" % (group_name, idx)] = str(exc)

            if group_data:
                grouped[group_name] = group_data

        if add_params:
            grouped["add_params"] = add_params

        if fetch_errors:
            grouped["__partial"] = True
            grouped["__errors__"] = fetch_errors

        return grouped


class Plugin(plugins.BasePlugin):
    __name__ = "ZTEROUTER"

    def run(self, config):
        ip = config.get(self.__name__, "ip")
        password = config.get(self.__name__, "password")

        username = None
        if config.has_option(self.__name__, "username"):
            username = config.get(self.__name__, "username")

        router = zteRouter(ip, username, password)
        router.authenticate()
        return router.fetch_api_info()


if __name__ == "__main__":
    Plugin().execute()
