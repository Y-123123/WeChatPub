"""Official API adapter. Requires actual API entitlement, not a login password."""
import json
import os
import time
from pathlib import Path

import requests


class WeChat:
    def __init__(self):
        self.appid = os.getenv("WECHAT_APP_ID", "")
        self.secret = os.getenv("WECHAT_APP_SECRET", "")
        if not self.appid or not self.secret:
            raise ValueError("未配置官方 API 凭据。有登录账号不等于有接口权限；无权限请使用本地文章包。")
        self.token = ""
        self.expiry = 0

    def _decode(self, response):
        if response.status_code != 200:
            raise RuntimeError(f"微信 API HTTP {response.status_code}，请求未自动重试。")
        try:
            # WeChat can label UTF-8 JSON as text/plain without a charset;
            # requests then assumes ISO-8859-1 and corrupts Chinese fields.
            response.encoding = "utf-8"
            result = response.json()
        except ValueError:
            raise RuntimeError("微信 API 返回非 JSON 响应，结果未知。") from None
        code = result.get("errcode", 0)
        if code:
            advice = {48001: "账号无此接口权限，请使用本地导出。", 40164: "请在公众号后台设置当前公网 IP 白名单。",
                      40001: "凭据或令牌无效。", 42001: "令牌过期。", 45009: "接口调用额度已用完。"}.get(code, "请查微信官方错误码说明。")
            raise RuntimeError(f"微信 API 错误 {code}：{advice}")
        return result

    def access_token(self):
        if self.token and time.monotonic() < self.expiry:
            return self.token
        try:
            r = requests.post("https://api.weixin.qq.com/cgi-bin/stable_token", json={"grant_type": "client_credential", "appid": self.appid, "secret": self.secret, "force_refresh": False}, timeout=30)
            result = self._decode(r)
        except requests.RequestException:
            raise RuntimeError("获取微信令牌失败；检查网络。") from None
        self.token = result["access_token"]
        self.expiry = time.monotonic() + max(0, int(result["expires_in"]) - 120)
        return self.token

    def call(self, endpoint, payload=None, file=None, params=None, method="POST"):
        token = self.access_token()
        try:
            kwargs = {"params": {"access_token": token, **(params or {})}, "timeout": 60}
            if method == "GET":
                r = requests.get("https://api.weixin.qq.com/cgi-bin/" + endpoint, **kwargs)
            elif file:
                with Path(file).open("rb") as stream:
                    r = requests.post("https://api.weixin.qq.com/cgi-bin/" + endpoint, files={"media": (Path(file).name, stream, "image/jpeg")}, **kwargs)
            else:
                r = requests.post("https://api.weixin.qq.com/cgi-bin/" + endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json; charset=utf-8"}, **kwargs)
            return self._decode(r)
        except requests.RequestException:
            # Mutations must not be retried blindly after ambiguous network failures.
            raise RuntimeError("微信请求中断，结果未知。请先核查后台，勿直接重发。") from None

    def upload_cover(self, path):
        return self.call("material/add_material", file=path, params={"type": "image"})["media_id"]

    def upload_inline(self, path):
        return self.call("media/uploadimg", file=path)["url"]

    def add_draft(self, article):
        return self.call("draft/add", {"articles": [article]})["media_id"]

    def get_draft(self, media_id):
        return self.call("draft/get", {"media_id": media_id})

    def update_draft(self, media_id, article):
        return self.call("draft/update", {"media_id": media_id, "index": 0, "articles": article})

    def submit(self, media_id):
        return self.call("freepublish/submit", {"media_id": media_id})["publish_id"]

    def status(self, publish_id):
        return self.call("freepublish/get", {"publish_id": publish_id})

    def check(self):
        """Read-only probes. A sibling endpoint working does not prove mutation permission."""
        self.access_token()
        checks = {}
        for label, endpoint, payload, method in [
            ("素材数量查询", "material/get_materialcount", None, "GET"),
            ("草稿数量查询", "draft/count", None, "GET"),
            ("已发布文章列表查询", "freepublish/batchget", {"offset": 0, "count": 1, "no_content": 1}, "POST"),
        ]:
            try:
                result = self.call(endpoint, payload=payload, method=method)
                checks[label] = {"available": True, "count": result.get("total_count", result.get("image_count"))}
            except RuntimeError as error:
                checks[label] = {"available": False, "error": str(error)}
        return {"checks": checks, "note": "这些是只读查询探测，不上传、不发布；查询成功不能证明 draft/add 或 freepublish/submit 权限，仍需核对后台。"}
