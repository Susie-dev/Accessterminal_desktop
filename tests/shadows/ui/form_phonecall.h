/**
 * @file form_phonecall.h
 * @brief **测试专用**的 `ui/form_phonecall.h` 影子头（室内机 Widget 测试）。
 *
 * 做法与门口机 tests/shadows/ui/widget.h 一致：命名为真头的名字
 * （`ui/form_phonecall.h`），用 `target_include_directories(... BEFORE PRIVATE ...)`
 * 插到真 `src/ui/form_phonecall.h` 之前。
 *
 * 为什么必须替掉真 `ui/form_phonecall.h`
 * --------------------------------------
 * 被测文件是**真实的 `src/ui/widget.cpp`**（383 行，此前从未被任何测试目标
 * 链接过）。它只用到 `Form_phonecall` 的一小块接口：
 *
 *   - `new Form_phonecall(nullptr, playRing)`
 *   - `setAttribute(Qt::WA_DeleteOnClose)` / `show()` / `close()`
 *   - 信号 `accepted` / `hangupClicked`（`Widget` 据此回 accept / recstop）
 *   - `QObject::destroyed`（清空 `m_callForm` / `m_callClient`）
 *
 * 而**真**头会拖进 `core/media/call_session.h`、`QMediaPlayer`（Qt5::Multimedia）、
 * `SlideHintWidget` 以及 `ui_form_phonecall.h` —— 那是整个通话浮层的门面，
 * 不是"测试 Widget 的编排逻辑"所需要的东西。用影子头只替掉这一层，
 * `widget.cpp` 本身一个字节都不改，走的仍是真实代码路径。
 *
 * 为什么必须带 Q_OBJECT
 * ---------------------
 * `Widget` 用 `connect(m_callForm, &Form_phonecall::accepted, ...)` 这类
 * **函数指针**语法连接信号。没有 Q_OBJECT 就没有 `Form_phonecall::accepted`
 * 这个符号，直接编译失败。
 *
 * 带 Q_OBJECT 则必须让 AUTOMOC 真的处理本头：AUTOMOC **不看 include 目录**，
 * 只处理列进 `add_executable` 源列表的文件。因此本头已显式列进
 * `desktop_test_widget` 的源列表（tests/CMakeLists.txt）。
 *
 * 安全阀
 * ------
 * 影子头会**顶掉**真正的应用头。为了绝不可能在产线目标里被误命中，
 * 这里要求必须显式定义 `ACC_WIDGET_TEST`；否则直接 `#error`。
 * 只有 `desktop_test_widget` 这一个目标会定义它。
 */
#ifndef ACCESSTERMINAL_TESTS_SHADOWS_FORM_PHONECALL_H
#define ACCESSTERMINAL_TESTS_SHADOWS_FORM_PHONECALL_H

#ifndef ACC_WIDGET_TEST
#  error "这个影子 ui/form_phonecall.h 只能用于测试；请在测试目标上定义 ACC_WIDGET_TEST"
#endif

#include <QWidget>

class Form_phonecall : public QWidget
{
    Q_OBJECT

public:
    explicit Form_phonecall(QWidget* parent = nullptr, bool playRing = true);
    ~Form_phonecall() override;

    /// 构造时传入的 playRing（"离线状态下不响铃"这条行为可断言）。
    bool ringRequested() const { return m_playRing; }

    /// 测试专用：模拟"用户把接听滑块拉到最右"。
    void emitAcceptedForTest() { emit accepted(); }
    /// 测试专用：模拟"用户点了挂断"。
    void emitHangupForTest() { emit hangupClicked(); }

signals:
    void answered();
    void accepted();
    void hangupClicked();

private:
    bool m_playRing = true;
};

#endif // ACCESSTERMINAL_TESTS_SHADOWS_FORM_PHONECALL_H
