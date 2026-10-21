/*
 * 游泳教练的内网接口。提问取回原文，再按原文下载 WAV 并从喇叭播出。
 */
#include "swim_coach.h"

#include "application.h"
#include "board.h"

#include <cJSON.h>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <memory>
#include <vector>

namespace {
std::atomic<bool> coach_cancel{false};
constexpr const char* kTag = "SwimCoach";
constexpr const char* kAskUrl = "http://192.168.5.2:8765/ask";
constexpr const char* kSpeakUrl = "http://192.168.5.2:8765/speak";
constexpr int kAskTimeoutMs = 90000;
constexpr int kSpeakTimeoutMs = 60000;
constexpr size_t kMaxQuestionBytes = 2000;
constexpr size_t kMaxSpeakBytes = 3000;
constexpr const char* kWaitLine = "好的，请稍等，我先查询一下数据。";
constexpr const char* kOldWaitLines[] = {
    "好的，请稍等，我先查询一下数据。",
    "好的，请稍等，我先看看您的训练数据。",
    "好的，请稍等。",
};

std::string StripWaitLine(std::string text) {
    bool changed = true;
    while (changed && !text.empty()) {
        changed = false;
        while (!text.empty() && (text.front() == ' ' || text.front() == '\n' || text.front() == '\r')) {
            text.erase(text.begin());
        }
        for (const char* prefix : kOldWaitLines) {
            const size_t length = std::strlen(prefix);
            if (text.compare(0, length, prefix) == 0) {
                text.erase(0, length);
                changed = true;
                break;
            }
        }
    }
    return text;
}

struct WavFormat {
    int sample_rate = 0;
    int channels = 0;
    int bits = 0;
    size_t data_offset = 0;
    bool ready = false;
};

uint32_t ReadLe32(const uint8_t* p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

uint16_t ReadLe16(const uint8_t* p) { return (uint16_t)p[0] | ((uint16_t)p[1] << 8); }

WavFormat ParseWavHeader(const uint8_t* data, size_t size) {
    WavFormat fmt;
    if (size < 12 || std::memcmp(data, "RIFF", 4) != 0 || std::memcmp(data + 8, "WAVE", 4) != 0) {
        return fmt;
    }
    size_t offset = 12;
    while (offset + 8 <= size) {
        const uint32_t chunk_size = ReadLe32(data + offset + 4);
        const uint8_t* payload = data + offset + 8;
        if (std::memcmp(data + offset, "fmt ", 4) == 0) {
            if (chunk_size < 16 || offset + 8 + 16 > size) {
                return fmt;
            }
            if (ReadLe16(payload) != 1) {
                return fmt;
            }
            fmt.channels = ReadLe16(payload + 2);
            fmt.sample_rate = (int)ReadLe32(payload + 4);
            fmt.bits = ReadLe16(payload + 14);
        } else if (std::memcmp(data + offset, "data", 4) == 0) {
            fmt.data_offset = offset + 8;
            fmt.ready = fmt.sample_rate > 0 && fmt.channels >= 1 && fmt.bits == 16;
            return fmt;
        }
        if (offset + 8 + chunk_size > size) {
            return fmt;
        }
        offset += 8 + chunk_size + (chunk_size & 1);
    }
    return fmt;
}

std::vector<int16_t> ToOutputRate(const int16_t* input, size_t count, int from_rate, int to_rate) {
    if (count == 0 || from_rate <= 0 || to_rate <= 0) {
        return {};
    }
    if (from_rate == to_rate) {
        return std::vector<int16_t>(input, input + count);
    }
    const size_t out_count = std::max<size_t>(1, (size_t)count * (size_t)to_rate / (size_t)from_rate);
    std::vector<int16_t> output(out_count);
    for (size_t i = 0; i < out_count; ++i) {
        const size_t src = std::min(count - 1, i * (size_t)from_rate / (size_t)to_rate);
        const size_t next = std::min(count - 1, src + 1);
        output[i] = (int16_t)(((int)input[src] + (int)input[next]) / 2);
    }
    return output;
}

bool PostJson(const char* url, const std::string& text, const char* session_id, int timeout_ms,
              std::unique_ptr<Http>& http) {
    cJSON* root = cJSON_CreateObject();
    if (root == nullptr) {
        return false;
    }
    cJSON_AddStringToObject(root, "text", text.c_str());
    if (session_id != nullptr) {
        cJSON_AddStringToObject(root, "session_id", session_id);
    }
    char* printed = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (printed == nullptr) {
        return false;
    }
    std::string body(printed);
    cJSON_free(printed);

    http = Board::GetInstance().GetNetwork()->CreateHttp(0);
    if (http == nullptr) {
        return false;
    }
    http->SetHeader("Content-Type", "application/json");
    http->SetTimeout(timeout_ms);
    http->SetContent(std::move(body));
    if (auto opened = http->Open("POST", url); !opened) {
        ESP_LOGE(kTag, "open failed: %s", opened.error().ToString().c_str());
        http->Close();
        return false;
    }
    return true;
}
}  // namespace

bool ReadNextLine(Http& http, std::string& pending, std::string& line) {
    while (pending.find('\n') == std::string::npos) {
        char buffer[512];
        auto read = http.Read(buffer, sizeof(buffer));
        if (!read) {
            return false;
        }
        if (*read <= 0 || SwimCoachCancelled()) {
            break;
        }
        pending.append(buffer, static_cast<size_t>(*read));
    }
    const auto pos = pending.find('\n');
    if (pos == std::string::npos) {
        line = std::move(pending);
        pending.clear();
        return !line.empty();
    }
    line = pending.substr(0, pos);
    pending.erase(0, pos + 1);
    if (!line.empty() && line.back() == '\r') {
        line.pop_back();
    }
    return true;
}

const char* CoachWaitLine() { return kWaitLine; }

std::string AskSwimCoach(const std::string& text, const std::function<void()>& on_query) {
    std::string question = text.size() > kMaxQuestionBytes ? text.substr(0, kMaxQuestionBytes) : text;
    if (question.empty()) {
        return "没有听清。";
    }

    std::unique_ptr<Http> http;
    if (!PostJson(kAskUrl, question, "epaper", kAskTimeoutMs, http)) {
        return "教练没有连上。";
    }

    auto status = http->GetStatusCode();
    if (!status || *status != 200) {
        ESP_LOGE(kTag, "status %d", status ? *status : 0);
        http->Close();
        return "教练没有答上来。";
    }

    std::string pending;
    std::string line;
    std::string result;
    bool saw_json = false;
    bool query_noted = false;
    while (ReadNextLine(*http, pending, line)) {
        if (line.empty()) {
            continue;
        }
        cJSON* root = cJSON_Parse(line.c_str());
        if (root == nullptr) {
            continue;
        }
        saw_json = true;
        cJSON* event = cJSON_GetObjectItem(root, "event");
        if (cJSON_IsString(event) && std::strcmp(event->valuestring, "wait") == 0 && !query_noted) {
            /* 查数时只改屏幕，不单独念固定句，避免每问都先播一句再播正文。 */
            query_noted = true;
            if (on_query) {
                on_query();
            }
        } else if (cJSON_IsString(event) && std::strcmp(event->valuestring, "reply") == 0) {
            cJSON* reply = cJSON_GetObjectItem(root, "text");
            result = (cJSON_IsString(reply) && reply->valuestring[0] != '\0') ? StripWaitLine(reply->valuestring)
                                                                               : "";
        } else {
            cJSON* reply = cJSON_GetObjectItem(root, "reply");
            if (cJSON_IsString(reply) && reply->valuestring[0] != '\0') {
                result = StripWaitLine(reply->valuestring);
            }
        }
        cJSON_Delete(root);
    }
    http->Close();
    if (!saw_json) {
        ESP_LOGE(kTag, "reply is not json");
        return "教练的回答读不出来。";
    }
    if (result.empty()) {
        result = "教练这次没有说出内容。";
    }
    ESP_LOGI(kTag, "reply %u bytes", static_cast<unsigned>(result.size()));
    return result;
}

std::vector<int16_t> DownloadCoachPcm(const std::string& spoken, int* output_rate) {
    std::vector<int16_t> pcm;
    std::unique_ptr<Http> http;
    if (!PostJson(kSpeakUrl, spoken, nullptr, kSpeakTimeoutMs, http)) {
        ESP_LOGE(kTag, "speak connect failed");
        return pcm;
    }
    auto status = http->GetStatusCode();
    if (!status || *status != 200) {
        ESP_LOGE(kTag, "speak status %d", status ? *status : 0);
        http->Close();
        return pcm;
    }

    /* 整段下完再播。边下边播时喇叭只留零点几秒，Wi-Fi 一慢整句就断。 */
    std::vector<uint8_t> body;
    body.reserve(64 * 1024);
    char chunk[1024];
    while (true) {
        auto read = http->Read(chunk, sizeof(chunk));
        if (!read) {
            ESP_LOGE(kTag, "speak read failed");
            http->Close();
            return {};
        }
        if (*read <= 0 || SwimCoachCancelled()) {
            break;
        }
        if (body.size() + static_cast<size_t>(*read) > 1536 * 1024) {
            ESP_LOGE(kTag, "speak wav too large");
            http->Close();
            return {};
        }
        body.insert(body.end(), chunk, chunk + *read);
    }
    http->Close();

    WavFormat fmt = ParseWavHeader(body.data(), body.size());
    if (!fmt.ready || fmt.bits != 16 || fmt.channels != 1 || fmt.data_offset >= body.size()) {
        ESP_LOGE(kTag, "speak wav %d Hz %d ch %d bit", fmt.sample_rate, fmt.channels, fmt.bits);
        return {};
    }
    const size_t samples = (body.size() - fmt.data_offset) / 2;
    if (samples == 0) {
        return {};
    }
    pcm.resize(samples);
    std::memcpy(pcm.data(), body.data() + fmt.data_offset, samples * sizeof(int16_t));

    auto* codec = Board::GetInstance().GetAudioCodec();
    const int rate = codec != nullptr ? codec->output_sample_rate() : 24000;
    if (output_rate != nullptr) {
        *output_rate = rate;
    }
    if (fmt.sample_rate != rate) {
        pcm = ToOutputRate(pcm.data(), pcm.size(), fmt.sample_rate, rate);
    }
    return pcm;
}

bool SpeakSwimCoach(const std::string& text, const std::function<void(int duration_ms)>& on_playback) {
    std::string spoken = text.size() > kMaxSpeakBytes ? text.substr(0, kMaxSpeakBytes) : text;
    if (spoken.empty()) {
        return false;
    }

    std::vector<int16_t> pcm;
    int output_rate = 24000;
    for (int attempt = 0; attempt < 2 && pcm.empty(); ++attempt) {
        if (attempt > 0) {
            vTaskDelay(pdMS_TO_TICKS(300));
        }
        pcm = DownloadCoachPcm(spoken, &output_rate);
    }
    if (pcm.empty() || output_rate <= 0) {
        ESP_LOGE(kTag, "speak failed");
        return false;
    }

    const int duration_ms =
        static_cast<int>((static_cast<int64_t>(pcm.size()) * 1000) / output_rate);
    auto& audio = Application::GetInstance().GetAudioService();
    audio.ResetDecoder();
    const uint32_t generation = audio.PlaybackGeneration();
    if (on_playback) {
        on_playback(std::max(duration_ms, 1));
    }
    /* 分小段送进喇叭。一整段一次写入时，中途失败就会这句完全没有声音。 */
    const size_t frame = std::max<size_t>(1, static_cast<size_t>(output_rate) * 400 / 1000);
    bool played = false;
    size_t offset = 0;
    while (offset < pcm.size() && !SwimCoachCancelled()) {
        const size_t count = std::min(frame, pcm.size() - offset);
        std::vector<int16_t> piece(pcm.begin() + static_cast<std::ptrdiff_t>(offset),
                                   pcm.begin() + static_cast<std::ptrdiff_t>(offset + count));
        offset += count;
        if (!audio.EnqueuePlaybackPcm(std::move(piece), generation)) {
            ESP_LOGE(kTag, "speak enqueue failed");
            break;
        }
        played = true;
    }
    if (played) {
        audio.WaitPlaybackIdle(generation, 120000);
        ESP_LOGI(kTag, "speak done");
    }
    return played;
}

struct SentenceItem {
    std::string text;
    bool end = false;
};

struct ClipItem {
    std::string text;
    std::vector<int16_t> pcm;
    int rate = 24000;
    bool end = false;
};

struct PlayPipeline {
    QueueHandle_t sentences = nullptr;
    QueueHandle_t clips = nullptr;
    SemaphoreHandle_t download_done = nullptr;
    SemaphoreHandle_t play_done = nullptr;
    std::function<void(const std::string&, int)> on_sentence;
};

void EnqueueClip(const std::vector<int16_t>& pcm, int output_rate, uint32_t generation) {
    const size_t frame = std::max<size_t>(1, static_cast<size_t>(output_rate) * 400 / 1000);
    size_t offset = 0;
    auto& audio = Application::GetInstance().GetAudioService();
    while (offset < pcm.size() && !SwimCoachCancelled()) {
        const size_t count = std::min(frame, pcm.size() - offset);
        std::vector<int16_t> piece(pcm.begin() + static_cast<std::ptrdiff_t>(offset),
                                   pcm.begin() + static_cast<std::ptrdiff_t>(offset + count));
        offset += count;
        if (!audio.EnqueuePlaybackPcm(std::move(piece), generation)) {
            ESP_LOGE(kTag, "speak enqueue failed");
            return;
        }
    }
}

void DownloadTask(void* arg) {
    auto* pipe = static_cast<PlayPipeline*>(arg);
    SentenceItem* item = nullptr;
    while (xQueueReceive(pipe->sentences, &item, portMAX_DELAY) == pdTRUE) {
        if (SwimCoachCancelled()) {
            delete item;
            auto* clip = new ClipItem();
            clip->end = true;
            xQueueSend(pipe->clips, &clip, portMAX_DELAY);
            break;
        }
        auto* clip = new ClipItem();
        if (item == nullptr || item->end) {
            clip->end = true;
            delete item;
            xQueueSend(pipe->clips, &clip, portMAX_DELAY);
            break;
        }
        clip->text = std::move(item->text);
        delete item;
        int rate = 24000;
        if (!SwimCoachCancelled()) {
            clip->pcm = DownloadCoachPcm(clip->text, &rate);
        }
        if (clip->pcm.empty() && !SwimCoachCancelled()) {
            vTaskDelay(pdMS_TO_TICKS(300));
            clip->pcm = DownloadCoachPcm(clip->text, &rate);
        }
        clip->rate = rate;
        xQueueSend(pipe->clips, &clip, portMAX_DELAY);
    }
    xSemaphoreGive(pipe->download_done);
    vTaskDelete(nullptr);
}

void PlaybackTask(void* arg) {
    auto* pipe = static_cast<PlayPipeline*>(arg);
    uint32_t generation = 0;
    bool started = false;
    ClipItem* clip = nullptr;
    while (xQueueReceive(pipe->clips, &clip, portMAX_DELAY) == pdTRUE) {
        if (clip == nullptr || clip->end || SwimCoachCancelled()) {
            delete clip;
            break;
        }
        int duration_ms = 0;
        if (!clip->pcm.empty() && clip->rate > 0) {
            duration_ms = static_cast<int>((static_cast<int64_t>(clip->pcm.size()) * 1000) / clip->rate);
        }
        if (pipe->on_sentence) {
            pipe->on_sentence(clip->text, duration_ms);
        }
        if (duration_ms > 0 && !SwimCoachCancelled()) {
            auto& audio = Application::GetInstance().GetAudioService();
            if (!started) {
                audio.ResetDecoder();
                generation = audio.PlaybackGeneration();
                started = true;
            }
            EnqueueClip(clip->pcm, clip->rate, generation);
        }
        delete clip;
    }
    if (started) {
        Application::GetInstance().GetAudioService().WaitPlaybackIdle(generation, 120000);
    }
    xSemaphoreGive(pipe->play_done);
    vTaskDelete(nullptr);
}

bool PushSentence(QueueHandle_t queue, const std::string& text, bool end) {
    auto* item = new SentenceItem();
    item->text = text;
    item->end = end;
    if (xQueueSend(queue, &item, portMAX_DELAY) != pdTRUE) {
        delete item;
        return false;
    }
    return true;
}

void CancelSwimCoach() { coach_cancel.store(true); }

void ClearSwimCoachCancel() { coach_cancel.store(false); }

bool SwimCoachCancelled() { return coach_cancel.load(); }

bool IsCoachGreeting(const std::string& text) {
    std::string compact;
    const char* greetings[] = {"你好小智", "你好", "您好", "在吗", "嗨", "哈喽", "hello", "hi", "小智"};
    for (size_t index = 0; index < text.size();) {
        const auto lead = static_cast<unsigned char>(text[index]);
        if (lead < 0x80) {
            if (std::isalnum(lead)) {
                compact.push_back(static_cast<char>(std::tolower(lead)));
            }
            ++index;
            continue;
        }
        size_t width = 1;
        if ((lead & 0xE0) == 0xC0) {
            width = 2;
        } else if ((lead & 0xF0) == 0xE0) {
            width = 3;
        } else if ((lead & 0xF8) == 0xF0) {
            width = 4;
        }
        if (index + width > text.size()) {
            break;
        }
        const std::string glyph = text.substr(index, width);
        if (glyph != "，" && glyph != "。" && glyph != "！" && glyph != "？" && glyph != "、" && glyph != " " &&
            glyph != "～") {
            compact += glyph;
        }
        index += width;
    }
    for (const char* greeting : greetings) {
        if (compact == greeting) {
            return true;
        }
    }
    return false;
}

bool IsCoachUnfocused(const std::string& text) {
    /* 短句仍交给教练。只有又长又没点名项目时，才在设备上直接问清楚。 */
    const char* cues[] = {"配速", "swolf", "SWOLF", "Swolf", "划水", "划次", "距离", "自由泳",
                          "蛙泳", "仰泳", "蝶泳", "混合泳", "多少", "几次", "后程", "前程",
                          "趋势", "耐力", "效率", "稳定", "负荷", "对比", "数据", "记录"};
    size_t chars = 0;
    for (size_t index = 0; index < text.size();) {
        const auto lead = static_cast<unsigned char>(text[index]);
        size_t width = 1;
        if (lead < 0x80) {
            width = 1;
        } else if ((lead & 0xE0) == 0xC0) {
            width = 2;
        } else if ((lead & 0xF0) == 0xE0) {
            width = 3;
        } else if ((lead & 0xF8) == 0xF0) {
            width = 4;
        }
        if (index + width > text.size()) {
            break;
        }
        if (!(lead < 0x80 && !std::isalnum(lead))) {
            ++chars;
        }
        index += width;
    }
    if (chars < 20) {
        return false;
    }
    for (const char* cue : cues) {
        if (text.find(cue) != std::string::npos) {
            return false;
        }
    }
    return true;
}

bool PlaySwimCoach(const std::string& text, const std::function<void()>& on_query,
                   const std::function<void(const std::string& sentence, int duration_ms)>& on_sentence) {
    ClearSwimCoachCancel();
    std::string question = text.size() > kMaxQuestionBytes ? text.substr(0, kMaxQuestionBytes) : text;
    if (question.empty()) {
        if (on_sentence) {
            on_sentence("没有听清。", 0);
        }
        return false;
    }

    PlayPipeline pipe;
    pipe.on_sentence = on_sentence;
    pipe.sentences = xQueueCreate(8, sizeof(SentenceItem*));
    pipe.clips = xQueueCreate(1, sizeof(ClipItem*));
    pipe.download_done = xSemaphoreCreateBinary();
    pipe.play_done = xSemaphoreCreateBinary();
    const bool queues_ready = pipe.sentences != nullptr && pipe.clips != nullptr && pipe.download_done != nullptr &&
                              pipe.play_done != nullptr;
    const bool download_started =
        queues_ready && xTaskCreate(DownloadTask, "coach_tts", 16384, &pipe, 3, nullptr) == pdPASS;
    const bool playback_started =
        download_started && xTaskCreate(PlaybackTask, "coach_play", 12288, &pipe, 3, nullptr) == pdPASS;
    if (!playback_started) {
        ESP_LOGE(kTag, "speak pipeline failed");
        if (download_started) {
            PushSentence(pipe.sentences, "", true);
            xSemaphoreTake(pipe.download_done, portMAX_DELAY);
        }
        if (on_sentence) {
            on_sentence("教练暂时开不了工。", 0);
        }
        if (pipe.sentences != nullptr) {
            vQueueDelete(pipe.sentences);
        }
        if (pipe.clips != nullptr) {
            vQueueDelete(pipe.clips);
        }
        if (pipe.download_done != nullptr) {
            vSemaphoreDelete(pipe.download_done);
        }
        if (pipe.play_done != nullptr) {
            vSemaphoreDelete(pipe.play_done);
        }
        return false;
    }

    std::unique_ptr<Http> http;
    bool ask_ok = PostJson(kAskUrl, question, "epaper", kAskTimeoutMs, http);
    int sentence_count = 0;
    std::string fallback;
    if (!ask_ok) {
        fallback = "教练没有连上。";
    } else {
        auto status = http->GetStatusCode();
        if (!status || *status != 200) {
            ESP_LOGE(kTag, "status %d", status ? *status : 0);
            http->Close();
            fallback = "教练没有答上来。";
        } else {
            std::string pending;
            std::string line;
            bool query_noted = false;
            bool saw_json = false;
            while (!SwimCoachCancelled() && ReadNextLine(*http, pending, line)) {
                if (line.empty()) {
                    continue;
                }
                cJSON* root = cJSON_Parse(line.c_str());
                if (root == nullptr) {
                    continue;
                }
                saw_json = true;
                cJSON* event = cJSON_GetObjectItem(root, "event");
                if (cJSON_IsString(event) && std::strcmp(event->valuestring, "wait") == 0 && !query_noted) {
                    query_noted = true;
                    if (on_query) {
                        on_query();
                    }
                } else if (cJSON_IsString(event) && std::strcmp(event->valuestring, "sentence") == 0) {
                    cJSON* reply = cJSON_GetObjectItem(root, "text");
                    if (cJSON_IsString(reply) && reply->valuestring[0] != '\0') {
                        std::string sentence = StripWaitLine(reply->valuestring);
                        if (!sentence.empty()) {
                            PushSentence(pipe.sentences, sentence, false);
                            ++sentence_count;
                        }
                    }
                } else if (cJSON_IsString(event) && std::strcmp(event->valuestring, "reply") == 0 &&
                           sentence_count == 0) {
                    cJSON* reply = cJSON_GetObjectItem(root, "text");
                    if (cJSON_IsString(reply) && reply->valuestring[0] != '\0') {
                        fallback = StripWaitLine(reply->valuestring);
                    }
                }
                cJSON_Delete(root);
            }
            http->Close();
            if (!saw_json) {
                fallback = "教练的回答读不出来。";
            } else if (sentence_count == 0 && fallback.empty()) {
                fallback = "教练这次没有说出内容。";
            }
        }
    }
    if (sentence_count == 0 && !fallback.empty()) {
        PushSentence(pipe.sentences, fallback, false);
    }
    PushSentence(pipe.sentences, "", true);
    xSemaphoreTake(pipe.download_done, portMAX_DELAY);
    xSemaphoreTake(pipe.play_done, portMAX_DELAY);
    vQueueDelete(pipe.sentences);
    vQueueDelete(pipe.clips);
    vSemaphoreDelete(pipe.download_done);
    vSemaphoreDelete(pipe.play_done);
    return sentence_count > 0 || !fallback.empty();
}
