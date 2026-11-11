import app as app_module


def test_loading_indicator_is_injected_into_html_only(tmp_path):
    application = app_module.create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'loading.sqlite').as_posix()}",
        }
    )

    @application.get("/loading-test")
    def loading_test():
        return "<html><body><main>Page</main></body></html>"

    @application.get("/loading-test.json")
    def loading_test_json():
        return {"ok": True}

    with application.test_client() as client:
        html_response = client.get("/loading-test")
        json_response = client.get("/loading-test.json")

    assert html_response.status_code == 200
    assert b'id="global-loading"' in html_response.data
    assert b"global-loading.css" in html_response.data
    assert b"global-loading.js" in html_response.data
    assert html_response.data.index(b'id="global-loading"') < html_response.data.index(b"</body>")
    assert json_response.get_json() == {"ok": True}
