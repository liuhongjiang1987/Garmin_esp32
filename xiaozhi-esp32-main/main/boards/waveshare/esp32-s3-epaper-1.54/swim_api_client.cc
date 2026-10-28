/*
 * 模块说明：ESP HTTP 客户端封装分析 API。
 */
#include "swim_api_client.h"

#include <cJSON.h>
#include <esp_http_client.h>
#include <esp_log.h>

#include <cstring>
#include <string>

namespace {

constexpr const char* kTag = "SwimApi";
/* 本机当前局域网地址；改网段后需同步更新，并保证 COACH_BIND=0.0.0.0。 */
constexpr const char* kBaseUrl = "http://192.168.5.2:8765";
constexpr int kTimeoutMs = 30000;

std::string HttpGet(const std::string& url, int* status_out) {
    std::string body;
    esp_http_client_config_t cfg = {};
    cfg.url = url.c_str();
    cfg.timeout_ms = kTimeoutMs;
    cfg.method = HTTP_METHOD_GET;
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == nullptr) {
        return body;
    }
    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        ESP_LOGE(kTag, "open fail %s", esp_err_to_name(err));
        esp_http_client_cleanup(client);
        return body;
    }
    (void)esp_http_client_fetch_headers(client);
    if (status_out) {
        *status_out = esp_http_client_get_status_code(client);
    }
    char buf[512];
    while (true) {
        int n = esp_http_client_read(client, buf, sizeof(buf));
        if (n <= 0) {
            break;
        }
        body.append(buf, n);
        if (body.size() > 200000) {
            break;
        }
    }
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return body;
}

std::string HttpPostJson(const std::string& url, const std::string& json, int* status_out) {
    std::string body;
    esp_http_client_config_t cfg = {};
    cfg.url = url.c_str();
    cfg.timeout_ms = kTimeoutMs;
    cfg.method = HTTP_METHOD_POST;
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == nullptr) {
        return body;
    }
    esp_http_client_set_header(client, "Content-Type", "application/json");
    const int write_len = static_cast<int>(json.size());
    esp_err_t err = esp_http_client_open(client, write_len);
    if (err != ESP_OK) {
        ESP_LOGE(kTag, "post open fail %s", esp_err_to_name(err));
        esp_http_client_cleanup(client);
        return body;
    }
    if (write_len > 0) {
        int written = esp_http_client_write(client, json.c_str(), write_len);
        if (written < 0) {
            ESP_LOGE(kTag, "post write fail");
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            return body;
        }
    }
    (void)esp_http_client_fetch_headers(client);
    if (status_out) {
        *status_out = esp_http_client_get_status_code(client);
    }
    char buf[512];
    while (true) {
        int n = esp_http_client_read(client, buf, sizeof(buf));
        if (n <= 0) {
            break;
        }
        body.append(buf, n);
        if (body.size() > 200000) {
            break;
        }
    }
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return body;
}

std::string HttpPost(const std::string& url, int* status_out) {
    return HttpPostJson(url, "{}", status_out);
}

std::string JsonStr(cJSON* obj, const char* key) {
    cJSON* n = cJSON_GetObjectItem(obj, key);
    if (cJSON_IsString(n) && n->valuestring) {
        return n->valuestring;
    }
    return {};
}

bool JsonBool(cJSON* obj, const char* key, bool def = false) {
    cJSON* n = cJSON_GetObjectItem(obj, key);
    if (cJSON_IsBool(n)) {
        return cJSON_IsTrue(n);
    }
    return def;
}

void ParseReport(cJSON* root, AnalysisReport* out) {
    out->pages.clear();
    out->charts.clear();
    cJSON* headline = cJSON_GetObjectItem(root, "headline");
    if (cJSON_IsObject(headline)) {
        out->one_liner = JsonStr(headline, "one_liner");
        out->sample_insufficient = JsonBool(headline, "sample_insufficient");
        cJSON* sc = cJSON_GetObjectItem(headline, "session_count");
        if (cJSON_IsNumber(sc)) {
            out->session_count = sc->valueint;
        }
    }
    cJSON* pages = cJSON_GetObjectItem(root, "pages");
    if (cJSON_IsArray(pages)) {
        cJSON* page = nullptr;
        cJSON_ArrayForEach(page, pages) {
            ReportPage rp;
            rp.page_id = JsonStr(page, "page_id");
            rp.title = JsonStr(page, "title");
            cJSON* metrics = cJSON_GetObjectItem(page, "metrics");
            if (cJSON_IsArray(metrics)) {
                cJSON* m = nullptr;
                cJSON_ArrayForEach(m, metrics) {
                    ReportPageMetric pm;
                    pm.label = JsonStr(m, "label");
                    pm.value = JsonStr(m, "value");
                    rp.metrics.push_back(pm);
                }
            }
            cJSON* notes = cJSON_GetObjectItem(page, "notes");
            if (cJSON_IsArray(notes)) {
                cJSON* n = nullptr;
                cJSON_ArrayForEach(n, notes) {
                    if (cJSON_IsString(n) && n->valuestring) {
                        rp.notes.push_back(n->valuestring);
                    }
                }
            }
            out->pages.push_back(std::move(rp));
        }
    }
    cJSON* charts = cJSON_GetObjectItem(root, "charts");
    if (cJSON_IsObject(charts)) {
        const char* keys[] = {"swolf", "pace", "distance"};
        for (const char* key : keys) {
            cJSON* c = cJSON_GetObjectItem(charts, key);
            if (!cJSON_IsObject(c)) {
                continue;
            }
            ChartSeries series;
            series.key = key;
            series.title = JsonStr(c, "title");
            series.note = JsonStr(c, "note");
            cJSON* points = cJSON_GetObjectItem(c, "points");
            if (cJSON_IsArray(points)) {
                cJSON* p = nullptr;
                cJSON_ArrayForEach(p, points) {
                    cJSON* v = cJSON_GetObjectItem(p, "value");
                    if (cJSON_IsNumber(v)) {
                        series.values.push_back(static_cast<float>(v->valuedouble));
                    }
                }
            }
            out->charts.push_back(std::move(series));
        }
    }
}

}  // namespace

bool SwimApiFetchSessions(std::vector<SessionListItem>* out, std::string* error) {
    if (out == nullptr) {
        return false;
    }
    out->clear();
    int status = 0;
    std::string body = HttpGet(std::string(kBaseUrl) + "/sessions?limit=20", &status);
    if (status != 200 || body.empty()) {
        if (error) {
            *error = "sessions http " + std::to_string(status);
        }
        return false;
    }
    cJSON* root = cJSON_Parse(body.c_str());
    if (!root) {
        if (error) {
            *error = "sessions json";
        }
        return false;
    }
    cJSON* items = cJSON_GetObjectItem(root, "items");
    if (cJSON_IsArray(items)) {
        cJSON* it = nullptr;
        cJSON_ArrayForEach(it, items) {
            SessionListItem row;
            row.activity_id = JsonStr(it, "activity_id");
            row.date = JsonStr(it, "date");
            row.status = JsonStr(it, "status");
            row.can_open = JsonBool(it, "can_open");
            cJSON* dist = cJSON_GetObjectItem(it, "distance_m");
            if (cJSON_IsNumber(dist)) {
                /* 对齐设计稿：1024米 */
                row.distance_text = std::to_string(static_cast<int>(dist->valuedouble)) + "米";
            }
            cJSON* sw = cJSON_GetObjectItem(it, "swolf");
            if (cJSON_IsNumber(sw)) {
                row.swolf_text = "SWOLF " + std::to_string(static_cast<int>(sw->valuedouble));
            }
            out->push_back(std::move(row));
        }
    }
    cJSON_Delete(root);
    return true;
}

bool SwimApiFetchTrends(std::vector<TrendListItem>* out, std::string* error) {
    if (out == nullptr) {
        return false;
    }
    out->clear();
    int status = 0;
    std::string body = HttpGet(std::string(kBaseUrl) + "/trends", &status);
    if (status != 200 || body.empty()) {
        if (error) {
            *error = "trends http " + std::to_string(status);
        }
        return false;
    }
    cJSON* root = cJSON_Parse(body.c_str());
    if (!root) {
        if (error) {
            *error = "trends json";
        }
        return false;
    }
    cJSON* items = cJSON_GetObjectItem(root, "items");
    if (cJSON_IsArray(items)) {
        cJSON* it = nullptr;
        cJSON_ArrayForEach(it, items) {
            TrendListItem row;
            row.span = JsonStr(it, "span");
            row.label = JsonStr(it, "label");
            row.status = JsonStr(it, "status");
            row.can_open = JsonBool(it, "can_open");
            row.cached = JsonBool(it, "cached");
            out->push_back(std::move(row));
        }
    }
    cJSON_Delete(root);
    return true;
}

bool SwimApiAnalyzeTrend(const std::string& span, TrendAnalyzeResult* out, std::string* error) {
    if (out == nullptr || span.empty()) {
        return false;
    }
    int status = 0;
    std::string body = HttpPost(std::string(kBaseUrl) + "/trends/" + span + "/analyze", &status);
    if (status != 200 || body.empty()) {
        if (error) {
            *error = "analyze http " + std::to_string(status);
        }
        return false;
    }
    cJSON* root = cJSON_Parse(body.c_str());
    if (!root) {
        if (error) {
            *error = "analyze json";
        }
        return false;
    }
    out->span = JsonStr(root, "span");
    out->label = JsonStr(root, "label");
    out->status = JsonStr(root, "status");
    out->can_open = JsonBool(root, "can_open");
    out->cached = JsonBool(root, "cached");
    out->started = JsonBool(root, "started");
    cJSON_Delete(root);
    return true;
}

bool SwimApiTrendStatus(const std::string& span, TrendAnalyzeResult* out, std::string* error) {
    if (out == nullptr || span.empty()) {
        return false;
    }
    int status = 0;
    std::string body = HttpGet(std::string(kBaseUrl) + "/trends/" + span + "/status", &status);
    if (status != 200 || body.empty()) {
        if (error) {
            *error = "status http " + std::to_string(status);
        }
        return false;
    }
    cJSON* root = cJSON_Parse(body.c_str());
    if (!root) {
        if (error) {
            *error = "status json";
        }
        return false;
    }
    out->span = JsonStr(root, "span");
    out->label = JsonStr(root, "label");
    out->status = JsonStr(root, "status");
    out->can_open = JsonBool(root, "can_open");
    out->cached = JsonBool(root, "cached");
    out->started = false;
    cJSON_Delete(root);
    return true;
}

bool SwimApiFetchSessionReport(const std::string& activity_id, AnalysisReport* out, std::string* error) {
    if (out == nullptr || activity_id.empty()) {
        return false;
    }
    int status = 0;
    std::string body = HttpGet(std::string(kBaseUrl) + "/sessions/" + activity_id + "/report", &status);
    if (status != 200 || body.empty()) {
        if (error) {
            *error = "session report http " + std::to_string(status);
        }
        return false;
    }
    cJSON* root = cJSON_Parse(body.c_str());
    if (!root) {
        if (error) {
            *error = "session report json";
        }
        return false;
    }
    ParseReport(root, out);
    cJSON_Delete(root);
    return true;
}

bool SwimApiFetchTrendReport(const std::string& span, AnalysisReport* out, std::string* error) {
    if (out == nullptr || span.empty()) {
        return false;
    }
    int status = 0;
    std::string body = HttpGet(std::string(kBaseUrl) + "/trends/" + span + "/report", &status);
    if (status != 200 || body.empty()) {
        if (error) {
            *error = "trend report http " + std::to_string(status);
        }
        return false;
    }
    cJSON* root = cJSON_Parse(body.c_str());
    if (!root) {
        if (error) {
            *error = "trend report json";
        }
        return false;
    }
    ParseReport(root, out);
    cJSON_Delete(root);
    return true;
}

bool SwimApiFetchAdviceProfile(AdviceProfile* out, std::string* error) {
    if (out == nullptr) {
        return false;
    }
    int status = 0;
    std::string body = HttpGet(std::string(kBaseUrl) + "/advice/profile", &status);
    if (status != 200 || body.empty()) {
        if (error) {
            *error = "advice profile http " + std::to_string(status);
        }
        return false;
    }
    cJSON* root = cJSON_Parse(body.c_str());
    if (!root) {
        if (error) {
            *error = "advice profile json";
        }
        return false;
    }
    out->has_profile = JsonBool(root, "has_profile");
    out->slots_complete = JsonBool(root, "slots_complete");
    out->summary_text = JsonStr(root, "summary_text");
    out->guide_text = JsonStr(root, "guide_text");
    out->modify_guide_text = JsonStr(root, "modify_guide_text");
    out->fields.clear();
    cJSON* fields = cJSON_GetObjectItem(root, "fields");
    if (cJSON_IsArray(fields)) {
        cJSON* it = nullptr;
        cJSON_ArrayForEach(it, fields) {
            AdviceProfileField f;
            f.label = JsonStr(it, "label");
            f.value = JsonStr(it, "value");
            if (!f.label.empty() && !f.value.empty()) {
                out->fields.push_back(std::move(f));
            }
        }
    }
    cJSON_Delete(root);
    return true;
}

bool SwimApiPostAdviceTurn(const std::string& text, AdviceTurnResult* out, std::string* error,
                           const char* mode) {
    if (out == nullptr) {
        return false;
    }
    cJSON* req = cJSON_CreateObject();
    if (req == nullptr) {
        if (error) {
            *error = "advice turn alloc";
        }
        return false;
    }
    cJSON_AddStringToObject(req, "text", text.c_str());
    cJSON_AddBoolToObject(req, "use_demo", false);
    cJSON_AddStringToObject(req, "mode", mode != nullptr ? mode : "interview");
    char* payload = cJSON_PrintUnformatted(req);
    cJSON_Delete(req);
    if (payload == nullptr) {
        if (error) {
            *error = "advice turn payload";
        }
        return false;
    }
    int status = 0;
    std::string body = HttpPostJson(std::string(kBaseUrl) + "/advice/turn", payload, &status);
    cJSON_free(payload);
    if (status != 200 || body.empty()) {
        if (error) {
            *error = "advice turn http " + std::to_string(status);
        }
        return false;
    }
    cJSON* root = cJSON_Parse(body.c_str());
    if (!root) {
        if (error) {
            *error = "advice turn json";
        }
        return false;
    }
    out->has_profile = JsonBool(root, "has_profile");
    out->summary_text = JsonStr(root, "summary_text");
    out->guide_text = JsonStr(root, "guide_text");
    out->reply_text = JsonStr(root, "reply_text");
    out->slots_complete = JsonBool(root, "slots_complete");
    out->start_plan = JsonBool(root, "start_plan");
    out->keep_listening = JsonBool(root, "keep_listening");
    out->fields.clear();
    cJSON* fields = cJSON_GetObjectItem(root, "fields");
    if (cJSON_IsArray(fields)) {
        cJSON* it = nullptr;
        cJSON_ArrayForEach(it, fields) {
            AdviceProfileField f;
            f.label = JsonStr(it, "label");
            f.value = JsonStr(it, "value");
            if (!f.label.empty() && !f.value.empty()) {
                out->fields.push_back(std::move(f));
            }
        }
    }
    cJSON* ps = cJSON_GetObjectItem(root, "plan_status");
    if (cJSON_IsObject(ps)) {
        out->plan_status.status = JsonStr(ps, "status");
        out->plan_status.can_open = JsonBool(ps, "can_open");
        out->plan_status.plan_id = JsonStr(ps, "plan_id");
    }
    cJSON_Delete(root);
    return true;
}

bool SwimApiFetchAdvicePlanStatus(AdvicePlanStatus* out, std::string* error) {
    if (out == nullptr) {
        return false;
    }
    int status = 0;
    std::string body = HttpGet(std::string(kBaseUrl) + "/advice/plan/status", &status);
    if (status != 200 || body.empty()) {
        if (error) {
            *error = "advice status http " + std::to_string(status);
        }
        return false;
    }
    cJSON* root = cJSON_Parse(body.c_str());
    if (!root) {
        if (error) {
            *error = "advice status json";
        }
        return false;
    }
    out->status = JsonStr(root, "status");
    out->can_open = JsonBool(root, "can_open");
    out->plan_id = JsonStr(root, "plan_id");
    cJSON_Delete(root);
    return true;
}

bool SwimApiFetchAdvicePlan(AdvicePlan* out, std::string* error) {
    if (out == nullptr) {
        return false;
    }
    out->pages.clear();
    int status = 0;
    std::string body = HttpGet(std::string(kBaseUrl) + "/advice/plan", &status);
    if (status != 200 || body.empty()) {
        if (error) {
            *error = "advice plan http " + std::to_string(status);
        }
        return false;
    }
    cJSON* root = cJSON_Parse(body.c_str());
    if (!root) {
        if (error) {
            *error = "advice plan json";
        }
        return false;
    }
    out->plan_id = JsonStr(root, "plan_id");
    cJSON* pages = cJSON_GetObjectItem(root, "pages");
    if (cJSON_IsArray(pages)) {
        cJSON* it = nullptr;
        cJSON_ArrayForEach(it, pages) {
            PlanPage page;
            page.title = JsonStr(it, "title");
            page.repeat_badge = JsonStr(it, "repeat_badge");
            cJSON* metrics = cJSON_GetObjectItem(it, "metrics");
            if (cJSON_IsArray(metrics)) {
                cJSON* m = nullptr;
                cJSON_ArrayForEach(m, metrics) {
                    ReportPageMetric pm;
                    pm.label = JsonStr(m, "label");
                    pm.value = JsonStr(m, "value");
                    page.metrics.push_back(std::move(pm));
                }
            }
            out->pages.push_back(std::move(page));
        }
    }
    cJSON_Delete(root);
    return !out->pages.empty();
}

bool SwimApiAnalyzeAdvicePlan(bool use_demo, AdvicePlanStatus* out, std::string* error) {
    if (out == nullptr) {
        return false;
    }
    int status = 0;
    std::string url = std::string(kBaseUrl) + "/advice/plan/analyze?use_demo=" + (use_demo ? "true" : "false");
    std::string body = HttpPost(url, &status);
    if (status != 200 || body.empty()) {
        if (error) {
            *error = "advice analyze http " + std::to_string(status);
        }
        return false;
    }
    cJSON* root = cJSON_Parse(body.c_str());
    if (!root) {
        if (error) {
            *error = "advice analyze json";
        }
        return false;
    }
    out->status = JsonStr(root, "status");
    out->can_open = JsonBool(root, "can_open");
    out->plan_id = JsonStr(root, "plan_id");
    cJSON_Delete(root);
    return true;
}
