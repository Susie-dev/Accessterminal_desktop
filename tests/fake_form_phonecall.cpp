/**
 * @file fake_form_phonecall.cpp
 * @brief 影子 `Form_phonecall` 的实现与记录定义。
 *
 * 这里包含的是**影子** `ui/form_phonecall.h`（靠 include 路径顺序命中），
 * 与 `widget.cpp` 编译时看到的必须是同一个头，否则两边对类型的理解不一致。
 */
#include "ui/form_phonecall.h"

#include "fake_form_phonecall.h"

namespace {

FakeFormRecord g_record;

} // namespace

FakeFormRecord& fakeForm()
{
    return g_record;
}

void resetFakeForm()
{
    g_record = FakeFormRecord();
}

Form_phonecall::Form_phonecall(QWidget* parent, bool playRing)
    : QWidget(parent)
    , m_playRing(playRing)
{
    ++fakeForm().constructed;
    fakeForm().lastPlayRing = playRing;
    fakeForm().last = this;
}

Form_phonecall::~Form_phonecall()
{
    ++fakeForm().destroyed;
    if (fakeForm().last == this) {
        fakeForm().last = nullptr;
    }
}
