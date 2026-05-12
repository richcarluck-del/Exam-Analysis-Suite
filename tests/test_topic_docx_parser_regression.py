from analyzer.app.knowledge_point_parser import (
    KnowledgePointIngestionService,
    TopicQuestionSegment,
    _topic_segment_is_numbered_explanatory_statement,
)
from analyzer.app.question_bank_parser import (
    ExtractedOption,
    ExtractedQuestion,
    QuestionBankIngestionService,
)


def _make_question(
    *,
    question_no: str,
    original_label: str,
    stem_text: str,
    question_type: str = "subjective",
    options=None,
    answer_text=None,
    analysis_text=None,
    solution_text=None,
):
    return ExtractedQuestion(
        question_no=question_no,
        original_question_label=original_label,
        text=stem_text,
        question_type=question_type,
        has_formula=False,
        stem_text=stem_text,
        options=list(options or []),
        answer_text=answer_text,
        analysis_text=analysis_text,
        solution_text=solution_text,
    )


def test_numbered_explanatory_statement_is_not_treated_as_question():
    text = "2.利用函数的周期性，可将其他区间上的求值、求零点个数、求解析式等问题，转化到已知区间上，进而解决问题。"
    assert _topic_segment_is_numbered_explanatory_statement(text) is True


def test_grouped_subquestion_rebuild_preserves_shared_answer_and_second_prompt():
    svc = KnowledgePointIngestionService()
    qbs = QuestionBankIngestionService()
    seg = TopicQuestionSegment(
        question_no="对点练.(1)",
        section_title="未命名区域",
        blocks=[
            {
                "text": (
                    "对点练.(1)(2023新课标卷)若f(x)=lnx为偶函数，则a=( )\n"
                    "A.-1    B.0\n"
                    "C.1     D.2\n"
                    "(2)(2025山东青岛模拟)已知f(x)是定义在R上的偶函数，当x>=0时，f(x)=2x-2，则不等式f(x)<=0的解集是 .\n"
                    "答案：(1)B (2)[-2,2]\n"
                    "解析：(1)法一：......\n"
                    "(2)因为当x>=0时，f(x)=2x-2，所以偶函数f(x)在[-2,2]内满足条件。"
                )
            }
        ],
        block_index_start=0,
        block_index_end=1,
    )
    broken = _make_question(
        question_no="1",
        original_label="对点练.(1)",
        question_type="choice",
        stem_text="对点练.(1)(2023新课标卷)若f(x)=lnx为偶函数，则a=( )",
        options=[
            ExtractedOption(option_key="A", option_text="-1"),
            ExtractedOption(option_key="B", option_text="0"),
            ExtractedOption(option_key="C", option_text="1"),
            ExtractedOption(
                option_key="D",
                option_text="2(2)(2025山东青岛模拟)已知f(x)是定义在R上的偶函数，当x>=0时，f(x)=2x-2，则不等式f(x)<=0的解集是 .",
            ),
        ],
        answer_text="B",
        analysis_text="(1)法一：......",
    )

    rebuilt = svc._rebuild_grouped_topic_plaintext_question(qbs, seg, broken)
    rebuilt = svc._postprocess_topic_extracted_question(
        qbs,
        rebuilt,
        seg.question_no,
        preserve_grouped_subquestions=True,
    )

    assert "(2)(2025山东青岛模拟)" in (rebuilt.stem_text or "")
    assert rebuilt.answer_text == "(1)B (2)[-2,2]"
    assert "(2)因为当x>=0时" in (rebuilt.analysis_text or "")


def test_solution_tail_segment_merges_back_into_previous_grouped_question():
    svc = KnowledgePointIngestionService()
    qbs = QuestionBankIngestionService()
    prev = _make_question(
        question_no="8",
        original_label="3",
        stem_text="判断下列函数的奇偶性：\n(1)......\n(2)......\n(3)......\n(4)f(x)=",
        solution_text="(1)......\n(2)......\n(3)......",
    )
    tail = _make_question(
        question_no="9",
        original_label="(4)",
        stem_text="(4)法一：定义法......\n法二：图象法......",
    )
    prev_seg = TopicQuestionSegment(
        question_no="3",
        section_title="考点一",
        blocks=[{"text": prev.stem_text}],
        block_index_start=10,
        block_index_end=11,
    )
    tail_seg = TopicQuestionSegment(
        question_no="(4)",
        section_title="考点一",
        blocks=[{"text": tail.stem_text}],
        block_index_start=11,
        block_index_end=12,
    )

    merged_questions, merged_segments = svc._merge_trailing_solution_only_topic_questions(
        qbs,
        [prev, tail],
        [prev_seg, tail_seg],
    )

    assert len(merged_questions) == 1
    assert len(merged_segments) == 1
    assert "(4)法一" in (merged_questions[0].solution_text or "")


def test_grouped_choice_answer_forces_plaintext_rebuild_and_absorbs_analysis_tail():
    svc = KnowledgePointIngestionService()
    qbs = QuestionBankIngestionService()
    seg = TopicQuestionSegment(
        question_no="8",
        section_title="第四节",
        blocks=[
            {
                "text": (
                    "(1)函数y=f(1-x)的图象与函数y=f(2+x)的图象关于直线x=m对称，其中m=( )\n"
                    "A.3 B.1 C.-1 D.-2\n"
                    "(2)下列函数与y=2x-cos x的图象关于原点对称的函数是( )\n"
                    "A.g(x)=-2x-cos(-x) B.g(x)=2x+cos(-x) C.g(x)=-2x+cos(-x) D.g(x)=2x-cos(-x)\n"
                    "答案：(1)D (2)C"
                )
            }
        ],
        block_index_start=0,
        block_index_end=1,
    )
    broken = _make_question(
        question_no="8",
        original_label="8",
        question_type="choice",
        stem_text="(1)函数y=f(1-x)的图象与函数y=f(2+x)的图象关于直线x=m对称，其中m=( )",
        options=[
            ExtractedOption(option_key="A", option_text="3"),
            ExtractedOption(option_key="B", option_text="g(x)=-2x+cos x\ng(x)=-cos(-x)"),
            ExtractedOption(option_key="C", option_text="-1"),
            ExtractedOption(option_key="D", option_text="-2下列函数与y=2x-cos x的图象关于原点对称的函数是( )"),
        ],
        answer_text="(1)D (2)C",
    )

    assert svc._topic_segment_needs_grouped_plaintext_rebuild(seg, broken) is True

    rebuilt = svc._rebuild_grouped_topic_plaintext_question(qbs, seg, broken)
    rebuilt = svc._postprocess_topic_extracted_question(
        qbs,
        rebuilt,
        seg.question_no,
        preserve_grouped_subquestions=True,
    )

    assert rebuilt.options == []
    assert "(2)下列函数与y=2x-cos x的图象关于原点对称的函数是( )" in (rebuilt.stem_text or "")
    assert rebuilt.answer_text == "(1)D (2)C"

    tail = _make_question(
        question_no="9",
        original_label="9",
        stem_text="设点P(x，y)在函数y=f(1-x)的图象上，故选D．\n(2)令f(x)=2x-cos x，则g(x)=-f(-x).故选C．",
    )
    tail_seg = TopicQuestionSegment(
        question_no="9",
        section_title="第四节",
        blocks=[{"text": tail.stem_text}],
        block_index_start=1,
        block_index_end=2,
    )

    merged_questions, merged_segments = svc._merge_trailing_solution_only_topic_questions(
        qbs,
        [rebuilt, tail],
        [seg, tail_seg],
    )

    assert len(merged_questions) == 1
    assert len(merged_segments) == 1
    assert "故选D" in (merged_questions[0].solution_text or "")
    assert "故选C" in (merged_questions[0].solution_text or "")
