from datetime import datetime
from flask import render_template, request
from run import app
from wxcloudrun.dao import delete_counterbyid, query_counterbyid, insert_counter, update_counterbyid
from wxcloudrun.model import Counters
from wxcloudrun.response import make_succ_empty_response, make_succ_response, make_err_response
import os
import time
import requests
import urllib3
from requests.exceptions import SSLError


_WECHAT_TOKEN_CACHE = {"token": "", "expire_at": 0}
_WECHAT_API_BASE = "https://api.weixin.qq.com"


def _wechat_get(path, *, params=None, timeout=20):
    url = f"{_WECHAT_API_BASE}{path}"
    try:
        return requests.get(url, params=params, timeout=timeout).json()
    except SSLError:
        # Some cloud environments may have custom TLS interception certs.
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return requests.get(url, params=params, timeout=timeout, verify=False).json()


def _wechat_post(path, *, params=None, json_body=None, files=None, timeout=40):
    url = f"{_WECHAT_API_BASE}{path}"
    try:
        return requests.post(url, params=params, json=json_body, files=files, timeout=timeout).json()
    except SSLError:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return requests.post(
            url,
            params=params,
            json=json_body,
            files=files,
            timeout=timeout,
            verify=False,
        ).json()


def _get_wechat_access_token():
    now = int(time.time())
    if _WECHAT_TOKEN_CACHE["token"] and now < _WECHAT_TOKEN_CACHE["expire_at"]:
        return _WECHAT_TOKEN_CACHE["token"]

    app_id = os.getenv("WECHAT_APP_ID") or os.getenv("APP_ID")
    app_secret = os.getenv("WECHAT_APP_SECRET") or os.getenv("APP_SECRET")
    if not app_id or not app_secret:
        raise RuntimeError("缺少环境变量 WECHAT_APP_ID/WECHAT_APP_SECRET（或 APP_ID/APP_SECRET）")

    resp = _wechat_get(
        "/cgi-bin/token",
        params={
            "grant_type": "client_credential",
            "appid": app_id,
            "secret": app_secret,
        },
        timeout=20,
    )
    token = resp.get("access_token")
    if not token:
        raise RuntimeError(f"获取 access_token 失败: {resp}")

    expires_in = int(resp.get("expires_in", 7200))
    _WECHAT_TOKEN_CACHE["token"] = token
    _WECHAT_TOKEN_CACHE["expire_at"] = now + max(300, expires_in - 300)
    return token


def _download_then_upload_permanent_image(token, image_url):
    dl = requests.get(image_url, timeout=30)
    dl.raise_for_status()

    content_type = dl.headers.get("Content-Type", "image/jpeg")
    filename = "image.jpg"
    if "png" in content_type.lower():
        filename = "image.png"

    up = _wechat_post(
        "/cgi-bin/material/add_material",
        params={"access_token": token, "type": "image"},
        files={"media": (filename, dl.content, content_type)},
        timeout=40,
    )
    media_id = up.get("media_id")
    if not media_id:
        raise RuntimeError(f"上传永久素材失败: {up}")
    return media_id


@app.route('/')
def index():
    """
    :return: 返回index页面
    """
    return render_template('index.html')


@app.route('/api/count', methods=['POST'])
def count():
    """
    :return:计数结果/清除结果
    """

    # 获取请求体参数
    params = request.get_json()

    # 检查action参数
    if 'action' not in params:
        return make_err_response('缺少action参数')

    # 按照不同的action的值，进行不同的操作
    action = params['action']

    # 执行自增操作
    if action == 'inc':
        counter = query_counterbyid(1)
        if counter is None:
            counter = Counters()
            counter.id = 1
            counter.count = 1
            counter.created_at = datetime.now()
            counter.updated_at = datetime.now()
            insert_counter(counter)
        else:
            counter.id = 1
            counter.count += 1
            counter.updated_at = datetime.now()
            update_counterbyid(counter)
        return make_succ_response(counter.count)

    # 执行清0操作
    elif action == 'clear':
        delete_counterbyid(1)
        return make_succ_empty_response()

    # action参数错误
    else:
        return make_err_response('action参数错误')


@app.route('/api/count', methods=['GET'])
def get_count():
    """
    :return: 计数的值
    """
    counter = Counters.query.filter(Counters.id == 1).first()
    return make_succ_response(0) if counter is None else make_succ_response(counter.count)


@app.route('/api/wechat/newspic/draft', methods=['POST'])
def create_newspic_draft():
    """
    创建公众号“图片消息(newspic)”草稿。
    请求示例：
    {
      "title": "贴图测试",
      "content": "3图测试",
      "image_urls": ["https://.../1.jpg", "https://.../2.jpg", "https://.../3.jpg"]
    }
    """
    try:
        params = request.get_json() or {}
        title = (params.get("title") or "").strip()
        content = (params.get("content") or "").strip()
        image_urls = params.get("image_urls") or []

        if not title:
            return make_err_response("缺少 title 参数")
        if not isinstance(image_urls, list) or len(image_urls) == 0:
            return make_err_response("image_urls 必须是非空数组")
        if len(image_urls) > 20:
            return make_err_response("image_urls 最多 20 张")

        token = _get_wechat_access_token()
        image_media_ids = []
        for u in image_urls:
            image_media_ids.append(_download_then_upload_permanent_image(token, u))

        payload = {
            "articles": [
                {
                    "article_type": "newspic",
                    "title": title,
                    "content": content if content else " ",
                    "need_open_comment": 0,
                    "only_fans_can_comment": 0,
                    "image_info": {
                        "image_list": [{"image_media_id": mid} for mid in image_media_ids]
                    },
                }
            ]
        }

        draft = _wechat_post(
            "/cgi-bin/draft/add",
            params={"access_token": token},
            json_body=payload,
            timeout=40,
        )

        if draft.get("media_id"):
            return make_succ_response({
                "draft_media_id": draft.get("media_id"),
                "image_media_ids": image_media_ids,
                "raw": draft
            })
        return make_err_response(f"draft/add 失败: {draft}")
    except Exception as e:
        return make_err_response(str(e))
