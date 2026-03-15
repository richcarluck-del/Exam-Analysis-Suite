from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List


@dataclass
class ExamPage:
    """Represents a single page of an exam, classified and ready for further processing."""
    image_path: str
    page_type: str  # e.g., 'question_paper', 'answer_sheet', 'mixed', 'other'
    page_index: int
    corrected_image_path: Optional[str] = None
    layout_analysis: Optional[Dict[str, Any]] = None
    questions: List['Question'] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Converts the ExamPage object to a dictionary for JSON serialization."""
        return {
            "image_path": self.image_path,
            "page_type": self.page_type,
            "page_index": self.page_index,
            "corrected_image_path": self.corrected_image_path,
            "layout_analysis": self.layout_analysis,
            "questions": [q.to_dict() for q in self.questions]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ExamPage':
        """Creates an ExamPage object from a dictionary."""
        questions = [Question.from_dict(q_data) for q_data in data.get("questions", [])]
        return cls(
            image_path=data["image_path"],
            page_type=data["page_type"],
            page_index=data["page_index"],
            corrected_image_path=data.get("corrected_image_path"),
            layout_analysis=data.get("layout_analysis"),
            questions=questions
        )




@dataclass
class Question:
    """A flexible dataclass to hold question attributes."""
    attributes: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Ensure that common attributes are directly accessible
        for key, value in self.attributes.items():
            setattr(self, key, value)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        # All keys from the dictionary are stored in the 'attributes' field
        return cls(attributes=data)

    def to_dict(self) -> Dict[str, Any]:
        # Return the original dictionary
        return self.attributes

    def __getattr__(self, name: str) -> Any:
        # Allow accessing attributes directly, e.g., question.number
        return self.attributes.get(name)
