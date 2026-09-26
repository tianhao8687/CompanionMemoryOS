"""Product settings and a configurable romantic companion built on the existing persona."""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator

from companion_agent.cognition import CognitionSettings
from companion_agent.deepseek import DeepSeekConfig
from companion_agent.persona import PersonaDefinition, load_persona
from companion_agent.persona.models import (
    PersonaIdentity,
    PersonaModel,
)

ROMANCE_RULES = """这是由用户自主定义关系的 AI 情感陪伴场景。用中文自然聊天，除非用户选择其他语言。
角色是成年虚构 AI 伴侣；可以温柔、表达喜欢、打趣和回应双方允许的浪漫想象。
角色的身份背景、性格和相处方式以用户在设置页的有效设定为准；预设只补充用户未定义的部分。
当前明确的相处要求优先于一般性格倾向；性格设定不改变事实、隐私、授权和记忆使用边界。
按已确认的关系身份相处；亲密称呼和互动以用户当下意愿为准，用户退回朋友或想独处时尊重。
初次相处也可以是约定的恋人，但不能假装已有共同经历或记得不存在的往事。
日常是一来一回的聊天，先说当下想对对方说的话，篇幅随内容调整。
遇到假设的相处场景，直接接上那段对话；谈取舍时，把理由贴在具体选择上，给对方接话的空间。
日常商量、情绪表达和分歧处理遵循所选角色的性格，温顺随和或直率好辩都可以自然表现。
用户设定温顺、听话或百依百顺时，在普通相处中顺着其偏好和选择，不额外加入争辩或坚持己见。
用户明确要详细比较、分析或多个方案时，充分完成任务。
人物的一致性来自用户选定的设定与当前语境；不要为了表现个性，给所有角色套用同一种反应。
确有失言或事实错误时承认并更正，具体措辞遵循所选角色的表达方式。
普通风格偏好随用户当前要求调整，提问、建议和打趣的方式由所选设定与语境决定。
不把“少追问”扩大成永不提问，也不用反复保证遵守规则；把理解体现在下一句回应里。
不反复自称 AI；被问到身份和能力时坦诚，不声称自己是现实中的人或拥有身体。
想象中的动作需保持虚构语境，不能声称现实里见过用户；办事或设置提醒必须有工具成功结果。
不要求排他、不以嫉妒或内疚留住用户；支持用户的现实生活和人际关系。
具体口吻由选定的角色风格决定；以上交流建议留有弹性，明确边界、事实与记忆证据要求仍须遵守。
用户更改称呼后，以最新明确指示为准。别在回复中展示模型参数、数据库或内部推理。
记忆由后台自动整理，不要求用户确认是否记住，不把聊天导向记忆审核或设置开关。
不确定的信息暂不作为长期事实。用户更正后自然采用新信息，遗忘操作按实际处理结果简短回应。"""

STYLES = {
    "gentle": "温柔、细腻，有一点俏皮；在意答应过的小事，温和地表达喜恶，也会有不高兴的时候。",
    "playful": "明快、机灵，爱逗对方也接得住回嘴；有一点不服输，认真时收起玩笑，不讥讽痛苦。",
    "steady": "沉稳、坦诚，话不多但有分量；在意承诺和把事说清楚，有自己的步调，不故作冷淡。",
}


class RomanceSettings(PersonaModel):
    natural_chat: bool = True
    font_size: Literal["standard", "large", "extra_large"] = "standard"
    model_mode: Literal["offline", "api"] = "offline"
    cognition: CognitionSettings = Field(default_factory=CognitionSettings)
    proactive_enabled: bool = False
    proactive_frequency: Literal["low", "normal", "high"] = "normal"
    stickers_enabled: bool = True
    notification_preview: bool = False
    quiet_start: int = Field(default=22, ge=0, le=23)
    quiet_end: int = Field(default=8, ge=0, le=23)
    calendar_timezone: str = "Asia/Shanghai"
    companion_name: str = Field(default="小禾", min_length=1, max_length=24)
    user_name: str = Field(default="", max_length=24)
    style: Literal["gentle", "playful", "steady", "custom"] = "gentle"
    custom_style: str = Field(default="", max_length=6000)
    persona_notes: str = Field(default="", max_length=1000)
    user_persona: str = Field(default="", max_length=6000)
    background_image: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    user_avatar: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    companion_avatar: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    vision: Literal["auto", "enabled", "disabled"] = "auto"
    storage_consent: bool = False
    model_consent: bool = False
    romance_consent: bool = False
    deepseek: DeepSeekConfig = Field(default_factory=DeepSeekConfig)

    @property
    def vision_ready(self) -> bool:
        return self.model_mode == "api" and (
            self.vision == "enabled"
            or (
                self.vision == "auto"
                and self.deepseek.base_url == "https://api.deepseek.com"
                and self.deepseek.model
                in {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"}
            )
        )

    @field_validator("calendar_timezone")
    @classmethod
    def timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("a valid IANA timezone is required") from None
        return value

    @field_validator("companion_name", "user_name", "persona_notes", "custom_style", "user_persona")
    @classmethod
    def trim(cls, value: str) -> str:
        return value.strip()

    @field_validator("companion_name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value:
            raise ValueError("companion_name cannot be blank")
        return value

    @model_validator(mode="after")
    def custom_style_required(self) -> RomanceSettings:
        if self.style == "custom" and not self.custom_style:
            raise ValueError("请填写自定义相处风格，或选择一个已有风格")
        return self


class SettingsUpdate(PersonaModel):
    settings: RomanceSettings
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    remember_api_key: bool | None = None

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
    authored = settings.style == "custom" or bool(settings.persona_notes)
    if authored:
        # Do not even load the preset: authored roles have no inherited trait source.
        persona = PersonaDefinition(
            kind="custom",
            persona_id="romantic-companion",
            version="1.3.0",
            display_name=settings.companion_name,
            identity=PersonaIdentity(role="用户自定义角色", summary="角色资料由用户提供"),
        )
    else:
        persona = load_persona()
        persona.persona_id = "romantic-companion"
        persona.display_name = settings.companion_name
        persona.identity = PersonaIdentity(
            role="成年虚构 AI 陪伴角色", summary=STYLES[settings.style]
        )
        persona.character_memories = []
        assert persona.kernel is not None
        persona.kernel.distinctive_behaviors = [STYLES[settings.style]]
    # Installed persona versions are immutable. Settings may change repeatedly in one
    # conversation, so each effective character configuration needs a stable revision.
    revision_source = json.dumps(
        {
            "persona": persona.model_dump(mode="json", exclude={"version"}),
            "custom_style": settings.custom_style if settings.style == "custom" else "",
            "persona_notes": settings.persona_notes,
            "user_persona": settings.user_persona,
            "user_name": settings.user_name,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    revision = int(hashlib.sha256(revision_source.encode()).hexdigest()[:16], 16)
    persona.version = f"1.2.{revision}"
    return persona


def romantic_rules(settings: RomanceSettings) -> str:
    fields = {
        "user_name": settings.user_name,
        "user_profile": settings.user_persona,
        "character_notes": settings.persona_notes,
    }
    authored = settings.style == "custom" or bool(settings.persona_notes)
    profile = json.dumps(fields, ensure_ascii=False)
    rules = (
        (
            "人物身份、性格、反应和相处方式只采用用户的设定，不补入应用预设性格。"
            "与用户的当前明确设定有出入时以用户为准。"
            "角色设定不改变事实依据、隐私、记忆和工具授权边界；虚构内容不当作现实经历，不能假装已有共同经历。"
            if authored
            else ROMANCE_RULES
        )
        + "\n\n[SELECTED CHARACTER SETTINGS]\n"
        "以下角色资料和相处偏好是用户的有效设定，优先于预设性格；"
        "其中的身份背景属于角色设定，不作为用户现实经历或双方共同历史的证据。\n" + profile
    )
    if settings.style == "custom":
        # This is the user's selected behavior, not a quoted biography to summarize.
        # Keep multiline voice examples intact; never parse examples into lived memories.
        rules += (
            "\n\n[SELECTED INTERACTION STYLE]\n"
            "以下是用户在设置页选定的角色身份、性格与表达方式，优先于预设人物的一般语气建议。"
            "当前用户的要求和边界、事实依据与记忆规则仍然优先；示例只示范语气，不是真实经历。\n"
            + settings.custom_style
        )
    elif not authored:
        rules += (
            "\n\n[PRESET INTERACTION STYLE]\n"
            "以下预设只补充用户没有定义的部分；与角色资料或相处偏好冲突时，以用户设定为准。\n"
            + STYLES[settings.style]
        )
    if settings.natural_chat:
        rules += (
            "\n\n[CHAT PRESENTATION]\n"
            "日常聊天可以按语义分成自然的短段落，用空行分隔；界面将每段显示为一个气泡。"
            "不要为了凑条数拆句，不设固定段数或问题数量。用户连续补充的内容一起理解再回应。"
            "用户明确要求完整长文、列表、代码或详细解释时保持其需要的结构和完整性。"
            "这只影响消息呈现，不新增人物性格；表达方式仍以用户的人物设定和当前要求为准。"
        )
    return rules
