/**
 * @file fake_form_phonecall.h
 * @brief 影子 `Form_phonecall` 的全局记录访问入口。
 *
 * 与 tests/fake_serial_port.h 同一套路：测试文件包含本头即可读取替身记录，
 * 不必（也不能）去包含真的 Qt/应用头。
 */
#ifndef ACCESSTERMINAL_TESTS_FAKE_FORM_PHONECALL_H
#define ACCESSTERMINAL_TESTS_FAKE_FORM_PHONECALL_H

class Form_phonecall;

/// 影子通话浮层记录下来的可观测量。
struct FakeFormRecord
{
    /// 累计构造次数（"收到 call 是否弹窗"、"是否重复弹窗"都看它）。
    int constructed = 0;
    /// 累计析构次数（"stopsend 是否真的关掉浮层"看它）。
    int destroyed = 0;
    /// 最近一次构造时传入的 playRing。
    bool lastPlayRing = true;
    /// 当前存活的那个实例；销毁后置空（供测试触发 accepted / hangup）。
    Form_phonecall* last = nullptr;
};

/// 取得全局替身记录。
FakeFormRecord& fakeForm();

/// 复位替身记录。
void resetFakeForm();

#endif // ACCESSTERMINAL_TESTS_FAKE_FORM_PHONECALL_H
