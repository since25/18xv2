// 把 115 STRM 的内网 OpenList 地址换成经服务器取流的地址，
// 客户端请求会先到 MediaWarp，再 302 到 115，家里和外网都能播放。
var OPENLIST_PREFIX = 'http://192.168.70.138:5244/';

// 依次从查询参数和各认证请求头取客户端令牌
function clientToken(r) {
    var h = r.headersIn;
    var direct = r.args.api_key || r.args.ApiKey || h['X-Emby-Token'] || h['X-MediaBrowser-Token'];
    if (direct) {
        return direct;
    }
    var auth = h['Authorization'] || h['X-Emby-Authorization'] || '';
    var m = auth.match(/Token="?([^",\s]+)"?/i);
    return m ? m[1] : '';
}

// 客户端访问服务器用的地址；没有转发协议头时，IP 或 localhost 按 http，域名按 https
function publicBase(r) {
    var host = r.headersIn['X-Forwarded-Host'] || r.headersIn['Host'] || '';
    var proto = r.headersIn['X-Forwarded-Proto'];
    if (!proto) {
        proto = /^(\d+\.\d+\.\d+\.\d+|localhost)(:\d+)?$/.test(host) ? 'http' : 'https';
    }
    return proto + '://' + host;
}

function rewriteSources(r, itemId, data) {
    var token = clientToken(r);
    var sources = data.MediaSources;
    if (!token || !Array.isArray(sources)) {
        return 0;
    }
    var base = publicBase(r);
    var count = 0;
    sources.forEach(function (source) {
        if (typeof source.Path !== 'string' || source.Path.indexOf(OPENLIST_PREFIX) !== 0) {
            return;
        }
        var stream = '/Videos/' + itemId + '/stream?MediaSourceId=' + encodeURIComponent(source.Id)
            + '&Static=true&api_key=' + encodeURIComponent(token);
        source.Path = base + stream;
        source.DirectStreamUrl = stream;
        count += 1;
    });
    return count;
}

function playbackInfo(r) {
    var itemId = r.uri.split('/')[2];
    r.subrequest('/__upstream' + r.uri, {
        method: r.method,
        args: r.variables.args || '',
        body: r.requestText || ''
    }).then(function (reply) {
        var body = reply.responseText;
        if (reply.status === 200) {
            try {
                var data = JSON.parse(body);
                if (rewriteSources(r, itemId, data) > 0) {
                    body = JSON.stringify(data);
                }
            } catch (e) {
                r.error('PlaybackInfo 解析失败: ' + e.message);
            }
        }
        r.headersOut['Content-Type'] = reply.headersOut['Content-Type'] || 'application/json';
        r.return(reply.status, body);
    }).catch(function (e) {
        r.error('PlaybackInfo 上游请求失败: ' + e.message);
        r.return(502);
    });
}

export default { playbackInfo };
