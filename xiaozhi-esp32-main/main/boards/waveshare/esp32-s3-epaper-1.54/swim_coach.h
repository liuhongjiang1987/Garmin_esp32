/*
 * 把小智识别出的一句话发给群晖上的游泳教练。
 * 屏幕和喇叭都使用教练返回的原文，不使用小智自己的回答。
 */
#pragma once

#include <functional>
#include <string>

const char* CoachWaitLine();
/* on_query 只在教练开始查游泳数据时调用一次，用来先把等待语显示出来。 */
std::string AskSwimCoach(const std::string& text, const std::function<void()>& on_query = {});
/* on_playback 在喇叭即将出声时调用，参数是这句音频的毫秒数，用来让翻页跟上声音。 */
bool SpeakSwimCoach(const std::string& text, const std::function<void(int duration_ms)>& on_playback = {});
/* 边收回答边播。每句合成好就出声，不等全文和整段音频都完成。on_sentence 的时长是这一句音频的毫秒数。 */
bool PlaySwimCoach(const std::string& text, const std::function<void()>& on_query,
                   const std::function<void(const std::string& sentence, int duration_ms)>& on_sentence);
/* 按键或新的一句进来时停掉正在播的教练声音。 */
void CancelSwimCoach();
void ClearSwimCoachCancel();
bool SwimCoachCancelled();
/* 只有打招呼，没有要查的内容。 */
bool IsCoachGreeting(const std::string& text);
/* 说得很长，但没有点名要查的项目。这种不交给教练查库。 */
bool IsCoachUnfocused(const std::string& text);
