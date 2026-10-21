#ifndef __CUSTOM_LCD_DISPLAY_H__
#define __CUSTOM_LCD_DISPLAY_H__

#include <driver/gpio.h>
#include <string>
#include <vector>
#include "lcd_display.h"

/* Display color */
typedef enum {
    DRIVER_COLOR_WHITE  = 0xff,
    DRIVER_COLOR_BLACK  = 0x00,
    FONT_BACKGROUND = DRIVER_COLOR_WHITE,
}COLOR_IMAGE;

typedef struct {
    uint8_t cs;
    uint8_t dc;
    uint8_t rst;
    uint8_t busy;
    uint8_t mosi;
    uint8_t scl;
    int spi_host;
    int buffer_len;
}custom_lcd_spi_t;


class CustomLcdDisplay : public LcdDisplay {
public:
    CustomLcdDisplay(esp_lcd_panel_io_handle_t panel_io, esp_lcd_panel_handle_t panel,
                  int width, int height, int offset_x, int offset_y,
                  bool mirror_x, bool mirror_y, bool swap_xy,custom_lcd_spi_t _lcd_spi_data);
    ~CustomLcdDisplay();

    void SetEmotion(const char* emotion) override;
    void SetStatus(const char* status) override;
    void SetChatMessage(const char* role, const char* content) override;
    void RemoveChatMessage(const char* role, const char* content) override;
    void ClearChatMessages() override;
    void SetupUI() override;

    /* 教练回答可能比小智会话更晚到，用这个接口强制写上整屏。 */
    void AppendChatTurn(const char* role, const char* content);
    /* 按这句话的音频时长翻页。duration_ms 为 0 时按阅读速度翻，用于没能播出的情况。 */
    void StartSpeechPages(int duration_ms);
    /* 又有一句可以念了。把这句接上，并按它的音频时长接着翻页。 */
    void NoteSpokenSentence(const std::string& sentence, int duration_ms);
    /* 教练请求还没返回时，回到待命也不要把已经写下的对话清掉。 */
    void HoldChat();
    void ReleaseChat();

    void EPD_Init();    /* 墨水屏初始化 */
    void EPD_Clear();   /* 清空屏幕 */
    void EPD_Display(); /* 刷buffer到墨水屏 */
    
    /*快速刷新*/
    void EPD_DisplayPartBaseImage();
    void EPD_Init_Partial();
    void EPD_DisplayPart();
    void EPD_DrawColorPixel(uint16_t x, uint16_t y,uint8_t color);
    
private:
    struct ChatSegment {
        std::string role;
        std::string text;
    };

    /* 待机（neutral）显示 Arena 字标，其它表情仍交给父类。 */
    void ShowStandbyLogo();
    /* 有字时标志收到状态栏下面，文字只占剩余区域，避免互相遮挡。 */
    void PlaceChatLayout(bool has_text);
    /* 正文按每页 4 行切好，播报时一页一页换，不再把整段滚到最后 4 行。 */
    void StopChatPages();
    void ShowChatPage(int page);
    std::vector<std::string> PaginateChat(const char* content);
    void EnterChatScreen();
    void ExitChatScreen();
    void AppendSegment(const char* role, const char* content);
    void RenderChat();

    lv_obj_t* chat_panel_ = nullptr;
    lv_obj_t* chat_label_ = nullptr;
    std::vector<ChatSegment> segments_;
    bool chat_active_ = false;
    bool standby_ = true;
    bool chat_text_visible_ = false;
    int hold_chat_ = 0;
    std::vector<std::string> chat_pages_;
    std::vector<int> page_switch_ms_;
    std::vector<int> page_codepoint_end_;
    std::vector<int> span_codepoint_end_;
    std::vector<int> span_audio_end_ms_;
    std::string spoken_text_;
    std::string shown_page_text_;
    int chat_page_ = 0;
    int audio_total_ms_ = 0;
    int64_t speech_started_us_ = 0;
    bool speech_clock_on_ = false;
    lv_timer_t* chat_page_timer_ = nullptr;
    void RebuildSpokenPages();
    void AdvanceSpokenPage();
    void EnsureSpeechTimer();

    const custom_lcd_spi_t lcd_spi_data;
    const int Width;
    const int Height;
    spi_device_handle_t spi;
    uint8_t *buffer = NULL;
    
    static void lvgl_flush_cb(lv_display_t * disp, const lv_area_t * area, uint8_t * color_p);
    
    void spi_gpio_init();
    void spi_port_init();
    void read_busy();

    void set_cs_1(){gpio_set_level((gpio_num_t)lcd_spi_data.cs,1);}
    void set_cs_0(){gpio_set_level((gpio_num_t)lcd_spi_data.cs,0);}
    void set_dc_1(){gpio_set_level((gpio_num_t)lcd_spi_data.dc,1);}
    void set_dc_0(){gpio_set_level((gpio_num_t)lcd_spi_data.dc,0);}
    void set_rst_1(){gpio_set_level((gpio_num_t)lcd_spi_data.rst,1);}
    void set_rst_0(){gpio_set_level((gpio_num_t)lcd_spi_data.rst,0);}

    void SPI_SendByte(uint8_t data);
    void EPD_SendData(uint8_t data);
    void EPD_SendCommand(uint8_t command);
    void writeBytes(uint8_t *buffer,int len);
    void writeBytes(const uint8_t *buffer, int len);
    void EPD_SetWindows(uint16_t Xstart, uint16_t Ystart, uint16_t Xend, uint16_t Yend);
    void EPD_SetCursor(uint16_t Xstart, uint16_t Ystart);
    void EPD_SetLut(const uint8_t *lut);
    void EPD_TurnOnDisplay();
    void EPD_TurnOnDisplayPart();
};

#endif // __CUSTOM_LCD_DISPLAY_H__