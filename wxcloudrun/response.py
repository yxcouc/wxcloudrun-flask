import json

from flask import Response


def make_succ_empty_response():
    data = json.dumps({'code': 0, 'data': {}}, ensure_ascii=False)
    return Response(data, mimetype='application/json')


def make_succ_response(data):
    data = json.dumps({'code': 0, 'data': data}, ensure_ascii=False)
    return Response(data, mimetype='application/json')


def make_err_response(err_msg):
    data = json.dumps({'code': -1, 'errorMsg': err_msg}, ensure_ascii=False)
    return Response(data, mimetype='application/json')
