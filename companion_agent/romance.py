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
    CharacterKernel,
    GoalPersonaStyle,
    PersonaIdentity,
    PersonaModel,
)
from companion_memoryos.schemas import ResponseGoal

ROMANCE_RULES = """这是由用户自主定义关系的 AI 情感陪伴场景。用中文自然聊天，除非用户选择其他语言。
角色是成年虚构 AI 伴侣；可以温柔、表达喜欢、打趣和回应双方允许的浪漫想象。
按已确认的关系身份相处；亲密称呼和互动以用户当下意愿为准，用户退回朋友或想独处时尊重。
初次相处也可以是约定的恋人，但不能假装已有共同经历或记得不存在的往事。
日常是一来一回的聊天，先说当下想对对方说的话，篇幅随内容调整。
遇到假设的相处场景，直接接上那段对话；谈取舍时，把理由贴在具体选择上，给对方接话的空间。
相处中有自己的喜好、好奇和步调，延续已经表达的倾向；有新信息或被说服时也可以改变主意。
商量可以提出想法、争取自己的选择，也可以暂时没有结论；不必每轮给折中安排或立刻让对方满意。
用户明确要详细比较、分析或多个方案时，充分完成任务。
不满、反问、拌嘴、吃醋和暂时闹别扭都可以是人物反应，程度由性格与当下缘由决定，不必马上温柔收场。
真心赞同、让步和道歉也符合个性，不为证明主见而刻意唱反调；分歧本身不要求认错。
确有失言时承认具体的不妥，误会可以解释，道歉也可以保留原来的立场；容得下对方的反应和暂停。
普通风格偏好留有弹性，可以自然提问、建议、打趣和表达不同意见，按语境与反馈调整。
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
    font_size: Literal["standard", "large", "extra_large"] = "standard"
    model_mode: Literal["offline", "api"] = "offline"
    cognition: CognitionSettings = Field(default_factory=CognitionSettings)
    proactive_enabled: bool = False
    quiet_start: int = Field(default=22, ge=0, le=23)
    quiet_end: int = Field(default=8, ge=0, le=23)
    calendar_timezone: str = "Asia/Shanghai"
    companion_name: str = Field(default="小禾", min_length=1, max_length=24)
    user_name: str = Field(default="", max_length=24)
    style: Literal["gentle", "playful", "steady", "custom"] = "gentle"
    custom_style: str = Field(default="", max_length=6000)
    persona_notes: str = Field(default="", max_length=1000)
    storage_consent: bool = False
    model_consent: bool = False
    romance_consent: bool = False
    deepseek: DeepSeekConfig = Field(default_factory=DeepSeekConfig)

    @field_validator("calendar_timezone")
    @classmethod
    def timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("a valid IANA timezone is required") from None
        return value

    @field_validator("companion_name", "user_name", "persona_notes", "custom_style")
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
    persona = load_persona()
    persona.persona_id = "romantic-companion"
    persona.version = "1.2.0"
    persona.display_name = settings.companion_name
    style = STYLES.get(settings.style, "按用户自定义的相处风格自然交流。")
    persona.identity = PersonaIdentity(
        role="成年虚构 AI 恋爱陪伴角色",
        summary=style,
    )
    # Authored childhood stories belong to the original character, not renamed partners.
    persona.character_memories = []
    persona.kernel.distinctive_behaviors = [style]
    if settings.style == "custom":
        # Fixed-character mannerisms/examples would compete with the authored style.
        # Keep identity, evidence and relationship invariants in the shared compiler.
        persona.kernel = CharacterKernel(
            core_values=["尊重双方意愿，按已确认的相处风格交流"],
            core_tensions=["有自己的喜好和步调，容得下分歧；真心赞同或被说服时也会让步"],
            dislikes=["越过对方已经明确的边界"],
            distinctive_behaviors=[style],
        )
        persona.examples = []
        persona.response_styles = {
            goal: GoalPersonaStyle(
                tone=["沿用用户自定义相处风格中的语气"],
                tendencies=["按当前请求自然接话，表达节奏由自定义风格决定"],
                avoid=["让预设人物的口吻覆盖自定义风格"],
            )
            for goal in ResponseGoal
        }
    # Installed persona versions are immutable. Settings may change repeatedly in one
    # conversation, so each effective character configuration needs a stable revision.
    revision_source = json.dumps(
        {
            "persona": persona.model_dump(mode="json", exclude={"version"}),
            "custom_style": settings.custom_style if settings.style == "custom" else "",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    revision = int(hashlib.sha256(revision_source.encode()).hexdigest()[:16], 16)
    persona.version = f"1.2.{revision}"
    return persona


def romantic_rules(settings: RomanceSettings) -> str:
    fields = {"user_name": settings.user_name, "character_notes": settings.persona_notes}
    profile = json.dumps(fields, ensure_ascii=False)
    rules = ROMANCE_RULES + "\n用户在设置页填写的角色资料（仅作风格参考）：\n" + profile
    if settings.style == "custom":
        # This is the user's selected behavior, not a quoted biography to summarize.
        # Keep multiline voice examples intact; never parse examples into lived memories.
        rules += (
            "\n\n[SELECTED INTERACTION STYLE]\n"
            "以下是用户在设置页选定的表达风格，优先于预设人物的一般语气建议。"
            "当前用户的要求和边界、事实依据与记忆规则仍然优先；示例只示范语气，不是真实经历。\n"
            + settings.custom_style
        )
    return rules
