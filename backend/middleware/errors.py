"""统一响应与错误码契约（Design Spec §6.3）。

成功 {code:0,data:...}；失败 {code:E,msg:...} + 4xx/5xx。
"""
from flask import jsonify


def ok(data=None, status=200):
    return jsonify({"code": 0, "data": data if data is not None else {}}), status


def err(code, msg, status=400):
    return jsonify({"code": code, "msg": msg}), status


def e_auth(msg="鉴权失败"):
    return err("E_AUTH", msg, 401)


def e_role(msg="无权操作"):
    return err("E_ROLE", msg, 403)


def e_forbidden(msg="无权访问该资源"):
    return err("E_FORBIDDEN", msg, 403)


def e_not_found(msg="资源不存在"):
    return err("E_NOT_FOUND", msg, 404)


def e_input(msg="参数不合法"):
    return err("E_INVALID_INPUT", msg, 400)


def e_rate(msg="调用过于频繁，请稍后再试"):
    return err("E_RATE", msg, 429)


def e_internal(msg="服务内部错误"):
    return err("E_INTERNAL", msg, 500)
