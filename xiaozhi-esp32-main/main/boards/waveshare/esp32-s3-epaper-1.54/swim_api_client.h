/*
 * 模块说明：表盘访问内网分析 API（列表 / 报告 / 趋势点选）。
 * 与旧 /ask 语音教练接口分离；基址与 swim_coach 同机。
 */
#pragma once

#include <string>
#include <vector>

struct SessionListItem {
    std::string activity_id;
    std::string date;
    std::string distance_text;
    std::string swolf_text;
    std::string status;  // analyzing|succeeded|failed
    bool can_open = false;
};

struct TrendListItem {
    std::string span;
    std::string label;
    std::string status;
    bool can_open = false;
    bool cached = false;
};

struct TrendAnalyzeResult {
    std::string span;
    std::string label;
    std::string status;
    bool can_open = false;
    bool cached = false;
    bool started = false;
};

struct ReportPageMetric {
    std::string label;
    std::string value;
};

struct ReportPage {
    std::string page_id;
    std::string title;
    std::vector<ReportPageMetric> metrics;
    std::vector<std::string> notes;
};

struct ChartSeries {
    std::string key;
    std::string title;
    std::string note;
    std::vector<float> values;
};

struct AnalysisReport {
    std::string one_liner;
    std::vector<ReportPage> pages;
    std::vector<ChartSeries> charts;
    bool sample_insufficient = false;
    int session_count = 0;
};

struct AdviceProfileField {
    std::string label;
    std::string value;
};

struct AdviceProfile {
    bool has_profile = false;
    bool slots_complete = false;
    std::string summary_text;
    std::string guide_text;
    std::string modify_guide_text; /* 修改档案二级页说明 */
    std::vector<AdviceProfileField> fields; /* 档案详情翻页 */
};

struct AdvicePlanStatus {
    std::string status;  // idle|analyzing|succeeded|failed
    bool can_open = false;
    std::string plan_id;
};

/* POST /advice/turn 一轮结果。 */
struct AdviceTurnResult {
    bool has_profile = false;
    std::string summary_text;
    std::string guide_text;
    std::string reply_text;
    bool slots_complete = false;
    bool start_plan = false;
    bool keep_listening = false; /* 改档未听清时继续开麦 */
    AdvicePlanStatus plan_status;
    std::vector<AdviceProfileField> fields;
};

struct PlanPage {
    std::string title;
    std::string repeat_badge;
    std::vector<ReportPageMetric> metrics;
};

struct AdvicePlan {
    std::string plan_id;
    std::vector<PlanPage> pages;
};

bool SwimApiFetchSessions(std::vector<SessionListItem>* out, std::string* error = nullptr);
bool SwimApiFetchTrends(std::vector<TrendListItem>* out, std::string* error = nullptr);
bool SwimApiAnalyzeTrend(const std::string& span, TrendAnalyzeResult* out, std::string* error = nullptr);
bool SwimApiTrendStatus(const std::string& span, TrendAnalyzeResult* out, std::string* error = nullptr);
bool SwimApiFetchSessionReport(const std::string& activity_id, AnalysisReport* out, std::string* error = nullptr);
bool SwimApiFetchTrendReport(const std::string& span, AnalysisReport* out, std::string* error = nullptr);
bool SwimApiFetchAdviceProfile(AdviceProfile* out, std::string* error = nullptr);
bool SwimApiPostAdviceTurn(const std::string& text, AdviceTurnResult* out, std::string* error = nullptr,
                           const char* mode = "interview");
bool SwimApiFetchAdvicePlanStatus(AdvicePlanStatus* out, std::string* error = nullptr);
bool SwimApiFetchAdvicePlan(AdvicePlan* out, std::string* error = nullptr);
bool SwimApiAnalyzeAdvicePlan(bool use_demo, AdvicePlanStatus* out, std::string* error = nullptr);
