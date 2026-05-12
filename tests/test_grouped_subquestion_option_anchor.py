from analyzer.app.question_bank_parser import QuestionBankIngestionService


def test_grouped_subquestions_keep_options_with_first_subquestion():
    qbs = QuestionBankIngestionService()

    def paragraph(text: str):
        return {
            "type": "paragraph",
            "style": {"line_spacing": 1.5},
            "children": [{"type": "text", "text": text, "marks": {}}],
        }

    polluted_stem_render = {
        "type": "block_group",
        "blocks": [
            paragraph("[图片](1)First subquestion asks for the matching option."),
            paragraph("(2)Second subquestion asks for a numeric answer."),
            paragraph("(3)Third subquestion asks for a proof."),
            paragraph("A. alpha    B. beta"),
            paragraph("C. gamma    D. delta"),
        ],
    }
    options_render = {
        "type": "block_group",
        "blocks": [
            paragraph("A. alpha    B. beta"),
            paragraph("C. gamma    D. delta"),
        ],
    }
    answer_render = {
        "type": "paragraph",
        "children": [{"type": "text", "text": "答案：(1)D (2)120", "marks": {}}],
    }

    question = qbs._parse_structured_question_segment(
        "5",
        [
            {
                "text": "[图片](1)First subquestion asks for the matching option.\n(2)Second subquestion asks for a numeric answer.\n(3)Third subquestion asks for a proof.\nA. alpha    B. beta\nC. gamma    D. delta",
                "render": polluted_stem_render,
            },
            {
                "text": "A. alpha    B. beta\nC. gamma    D. delta",
                "render": options_render,
            },
            {
                "text": "答案：(1)D (2)120",
                "render": answer_render,
            },
        ],
    )

    assert len(question.options) == 4
    assert question.stem_text.count("A.alpha") == 1
    assert question.stem_text.index("A.alpha") < question.stem_text.index("(2)")
    assert question.stem_text.index("D.delta") < question.stem_text.index("(2)")
    assert question.render_payloads["stem"]["plain_text"].count("A.alpha") == 0
