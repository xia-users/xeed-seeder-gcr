import os
import base64
import gzip
import json
import logging
from functools import wraps
from flask import Flask, request, Response, render_template, current_app
from google.cloud import pubsub_v1
import google.cloud.logging
from xialib.service import service_factory
from xialib_pubsub import PubsubPublisher, PubsubGcrPublisher
from pyxeed import Seeder

app = Flask(__name__)

app.config["INSIGHT"] = os.environ.get("XEED_INSIGHT", "")
app.config["DESTINATION"] = os.environ.get("XEED_DEST")
app.config["TOPIC_ID"] = os.environ.get("XEED_TOPIC")
app.config["SIZE_LIMIT"] = os.environ.get("XEED_SIZE_LIMIT", 0)

# Configuration Load
with open(os.path.join('.', 'config', 'global_conn_config.json')) as fp:
    global_conn_config = json.load(fp)
with open(os.path.join('.', 'config', 'object_config.json')) as fp:
    object_config = json.load(fp)

# Global Object Factory
global_connectors = service_factory(global_conn_config)


# Simple Authentification Service
def check(authorization_header):
    username = os.environ.get('XEED_USER', "user")  # Internal Usage oriented
    password = os.environ.get('XEED_PASSWORD', "La_vie_est_belle") # Internal Usage oriented
    encoded_uname_pass = authorization_header.split()[-1]
    if encoded_uname_pass == base64.b64encode((username + ":" + password).encode()).decode():
        return True

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        authorization_header = request.headers.get('Authorization')
        if authorization_header and check(authorization_header):
            return f(*args, **kwargs)
        else:
            resp = Response()
            resp.headers['WWW-Authenticate'] = 'Basic'
            return resp, 401
    return decorated

# Log configuration
client = google.cloud.logging.Client()
client.get_default_handler()
client.setup_logging()

@app.route('/')
def main():
    return render_template("index.html")

@app.route('/push',methods=['GET', 'POST'])
@login_required
def push():
    http_header_dict = dict(request.headers)
    msg_headers = {key.lower()[5:].replace('-', '_'): value for (key, value) in http_header_dict.items() if
                  key.lower().startswith('xeed-')}
    destination = current_app.config["DESTINATION"]
    topic_id = current_app.config["TOPIC_ID"]
    table_id = msg_headers.get('table_id', "")

    seeder = service_factory(object_config, global_connectors)

    if request.method == 'GET':
        if seeder.check_destination(destination, topic_id):
            return render_template("message.html", project=destination, topic=topic_id)
        else:
            return 'Destination/Topic not found', 400

    if http_header_dict.get('Content-Encoding', 'gzip') != 'gzip':
        return 'Content must be flat or gzip-encoded', 400

    if topic_id is None or table_id is None:
        return 'No topic_id or table_if found', 400
    msg_headers.update({'topic_id': topic_id, 'table_id': table_id})
    if any(key not in msg_headers for key in ['start_seq', 'data_encode', 'data_store', 'data_format']):
        return 'Xeed Header check error, something goeswrong', 400
    if msg_headers['data_store'] != 'body':
        content = request.data
    elif 'Content-Encoding' not in http_header_dict:
        if msg_headers['data_encode'] == 'flat':
            msg_headers['data_encode'] = 'gzip'
            content = gzip.compress(request.data)
        else:
            content = request.data
    else:
        if msg_headers['data_encode'] == 'flat':
            msg_headers['data_encode'] = 'gzip'
            content = request.data
        else:
            content = gzip.decompress(request.data)

    # Case 1: Send to Data Laker
    if current_app.config.get("INSIGHT", ""):
        default_seeder = Seeder(publisher=PubsubGcrPublisher())
        default_seeder.push_data(msg_headers, content,
                                 current_app.config["INSIGHT"], topic_id, table_id,
                                 current_app.config["SIZE_LIMIT"])
        logging.info("Data has been pushed to {}".format(current_app.config["INSIGHT"]))
    # Case 2: Send to Destination
    if current_app.config.get("INSIGHT", "") != current_app.config["DESTINATION"]:
        # insight == destination means save to insight data-lake only
        seeder.push_data(msg_headers, content, destination, topic_id, table_id, current_app.config["SIZE_LIMIT"])
        logging.info("Data has been pushed to {}".format(current_app.config["DESTINATION"]))
    return 'Data has been pushed to the destination', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))  # pragma: no cover