import copy
import logging
from req_parser.parser import RawRequestParser, RawRequest
from req_repeater.repeater import Repeater, Flow, Header
import time


# Configure logging to see the output from Request_repeater.py
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)


class GlassEngine:
    def __init__(self, RAW_BURP_REQUEST_INPUT):
        self.proxy_url = "http://127.0.0.1:8080"
        self.scheme_http = "https"
        self.original_request = self.parse_request(RAW_BURP_REQUEST_INPUT)
        self.safety_header_value = "Automated Test"
        self.platform_header = "X-Security-Research"
        self.platform_header_value = "[username]"


    # Parse the request
    def parse_request(self, RAW_BURP_REQUEST):
        try:
            original_request = RawRequestParser.parse(RAW_BURP_REQUEST)
            original_request.notes["scheme"] = self.scheme_http
            return original_request
        except Exception as e:
            print(f"[-] Failed to parse raw request: {e}")
            return False
    
    def copy_req(self):
        if not self.original_request:
            return False
        return copy.deepcopy(self.original_request)

    def final_mod(self, user_modified_request):
        final_modified_request = user_modified_request
        if final_modified_request.method == "GET" or final_modified_request.method == "HEAD":
                final_modified_request.body.raw = b""
                final_modified_request.body.parsed = None
                final_modified_request.body.content_type = None
                final_modified_request.headers = [
                    h for h in final_modified_request.headers 
                    if h.name.lower() not in ["content-length", "content-type"]
                ]
        return final_modified_request



    def create_flow(self, user_modified_request):
        with Repeater(timeout=15.0, verify=False, follow_redirects=False, proxy=self.proxy_url, version=self.original_request.version) as repeater:

            # Sleep for rate limit
            time.sleep(2)

            try:
                user_modified_request.headers.append(Header(name="X-Auto-cyb3rmehul", value=self.safety_header_value))
                user_modified_request.headers.append(Header(name=self.platform_header, value=self.platform_header_value))
                final_mod_request = self.final_mod(user_modified_request)
                flow = repeater.send(final_mod_request)
                return flow
                
            except Exception as e:
                print(f"[-] Network/Execution Error during request: {e}")
                return False
