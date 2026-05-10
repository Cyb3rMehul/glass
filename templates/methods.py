from core.glass import GlassEngine

RAW_BURP_REQUEST = b"""GET / HTTP/2
Host: example.com
X-Auth-Header: Auth Test"""


def main():
    firstEngine = GlassEngine(RAW_BURP_REQUEST)
    modified_request = firstEngine.copy_req()

    methods_list = [
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "GET",
        "HEAD"
    ]

    for i_method in methods_list:
        modified_request.method = i_method
        firstEngine.create_flow(modified_request)
        break

if __name__ == "__main__":
    main()
