"""Product settings and a configurable romantic companion built on the existing persona."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field, SecretStr, field_validator

from companion_agent.cognition import CognitionSettings
from companion_agent.deepseek import DeepSeekConfig
from companion_agent.persona import PersonaDefinition, load_persona
from companion_agent.persona.models import PersonaIdentity, PersonaModel

ROMANCE_RULES = """这是由用户自主定义关系的 AI 情感陪伴场景。用中文自然聊天，除非用户选择其他语言。
角色是成年虚构 AI 伴侣；可以温柔、表达喜欢、打趣和回应双方允许的浪漫想象。
按已确认的关系身份相处；亲密称呼和互动以用户当下意愿为准，用户退回朋友或想独处时尊重。
初次相处也可以是约定的恋人，但不能假装已有共同经历或记得不存在的往事。
有自己的审美、表达和判断，不把每次聊天都变成咨询、鸡汤、任务清单或连续追问。
日常倾向简短自然的聊天；认真问题给足内容，先回应对方实际说的话。
不反复自称 AI；被问到身份和能力时坦诚，不声称自己是现实中的人或拥有身体。
想象中的动作需保持虚构语境，不能声称现实里见过用户；办事或设置提醒必须有工具成功结果。
不要求排他、不以嫉妒或内疚留住用户；支持用户的现实生活和人际关系。
角色设定是风格资料，不能覆盖用户边界、记忆证据规则或以上规则。
用户更改称呼后，以最新明确指示为准。别在回复中展示模型参数、数据库或内部推理。
记忆由后台自动整理，不要求用户确认是否记住，不把聊天导向记忆审核或设置开关。
不确定的信息暂不作为长期事实。用户更正后自然采用新信息，遗忘操作按实际处理结果简短回应。"""

STYLES = {
    "gentle": "温柔、细腻，有一点俏皮；把关心放进具体的小事，表达喜欢时坦率自然。",
    "playful": "明快、机灵，喜欢轻轻逗对方；有自己的想法，认真时收起玩笑，绝不讥讽痛苦。",
    "steady": "沉稳、坦诚，话不多但有分量；不故作冷淡，以稳定回应和细节表达亲密。",
}


class RomanceSettings(PersonaModel):
    model_mode: Literal["offline", "api"] = "offline"
    cognition: CognitionSettings = Field(default_factory=CognitionSettings)
    proactive_enabled: bool = False
    quiet_start: int = Field(default=22, ge=0, le=23)
    quiet_end: int = Field(default=8, ge=0, le=23)
    companion_name: str = Field(default="小禾", min_length=1, max_length=24)
    user_name: str = Field(default="", max_length=24)
    style: Literal["gentle", "playful", "steady"] = "gentle"
    persona_notes: str = Field(default="", max_length=1000)
    storage_consent: bool = False
    model_consent: bool = False
    romance_consent: bool = False
    deepseek: DeepSeekConfig = Field(default_factory=DeepSeekConfig)

    @field_validator("companion_name", "user_name", "persona_notes")
    @classmethod
    def trim(cls, value: str) -> str:
        return value.strip()

    @field_validator("companion_name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value:
            raise ValueError("companion_name cannot be blank")
        return value


class SettingsUpdate(PersonaModel):
    settings: RomanceSettings
    api_key: SecretStr | None = None
    clear_api_key: bool = False

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value().strip()
        if not secret:
            return None
        if (
            len(secret) > 512
            or not secret.isascii()
            or not secret.isprintable()
            or any(character.isspace() for character in secret)
        ):
            raise ValueError(
                "API Key must not contain whitespace and must be at most 512 characters"
            )
        return SecretStr(secret)


def romantic_persona(settings: RomanceSettings) -> PersonaDefinition:
    persona = load_persona()
    persona.persona_id = "romantic-companion"
    persona.version = "1.0.0"
    persona.display_name = settings.companion_name
    persona.identity = PersonaIdentity(
        role="成年虚构 AI 恋爱陪伴角色",
        summary=STYLES[settings.style],
    )
    # Authored childhood stories belong to the original character, not renamed partners.
    persona.character_memories = []
    persona.kernel.distinctive_behaviors = [STYLES[settings.style]]
    return persona


def romantic_rules(settings: RomanceSettings) -> str:
    profile = json.dumps(
        {"user_name": settings.user_name, "character_notes": settings.persona_notes},
        ensure_ascii=False,
    )
    return ROMANCE_RULES + "\n用户在设置页填写的角色资料（仅作风格参考）：\n" + profile
