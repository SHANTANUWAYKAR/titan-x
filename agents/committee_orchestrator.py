"""
Module: committee_orchestrator.py
Description: Multi-agent investment committee orchestrator.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-06-28
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentVote:
    """Single agent vote on a trade proposal."""

    agent_name: str
    vote: str  # FOR, AGAINST, ABSTAIN
    reasoning: str
    confidence: int = 50


@dataclass
class CommitteeDecision:
    """Final committee decision on a trade proposal."""

    proposal_summary: str
    votes: list[AgentVote] = field(default_factory=list)
    consensus: str = "NO_CONSENSUS"
    cio_recommendation: str = ""
    risk_veto: bool = False
    human_approval_required: bool = True


class CommitteeOrchestrator:
    """
    Multi-agent investment committee debate manager.

    Flow: Trade Proposal → Agent Debate → Committee Vote →
    CIO Recommendation → Risk Veto Check → Human Approval
    """

    AGENTS = [
        "Macro Analyst",
        "Fundamental Analyst",
        "Technical Analyst",
        "Quant Researcher",
        "Microstructure Analyst",
        "Portfolio Manager",
        "Risk Manager",
        "Performance Auditor",
        "Knowledge Researcher",
        "Chief Investment Officer",
    ]

    def evaluate_proposal(self, proposal: dict[str, Any]) -> CommitteeDecision:
        """
        Run committee evaluation on a trade proposal.

        Args:
            proposal: Trade proposal with asset, direction, evidence, etc.

        Returns:
            CommitteeDecision with votes and recommendation.
        """
        votes: list[AgentVote] = []
        asset = proposal.get("asset", "UNKNOWN")
        direction = proposal.get("direction", "LONG")
        confidence = proposal.get("confidence_score", 0)

        # Rule-based agent simulation (LLM integration in Phase 2)
        votes.append(AgentVote(
            agent_name="Technical Analyst",
            vote="FOR" if confidence >= 80 else "AGAINST",
            reasoning=f"Technical score supports {direction} on {asset}",
            confidence=confidence,
        ))
        votes.append(AgentVote(
            agent_name="Risk Manager",
            vote="FOR" if proposal.get("risk_reward", 0) >= 2 else "AGAINST",
            reasoning="Risk:reward ratio evaluation",
            confidence=70,
        ))
        votes.append(AgentVote(
            agent_name="Portfolio Manager",
            vote="FOR" if confidence >= 75 else "ABSTAIN",
            reasoning="Portfolio heat and correlation check",
            confidence=60,
        ))

        for_count = sum(1 for v in votes if v.vote == "FOR")
        against_count = sum(1 for v in votes if v.vote == "AGAINST")

        if for_count > against_count:
            consensus = "BULLISH" if direction == "LONG" else "BEARISH"
            cio_rec = f"APPROVE {direction} on {asset} with reduced size if risk flags present"
        else:
            consensus = "REJECT"
            cio_rec = f"REJECT {direction} on {asset} — insufficient conviction"

        return CommitteeDecision(
            proposal_summary=f"{direction} {asset}",
            votes=votes,
            consensus=consensus,
            cio_recommendation=cio_rec,
            risk_veto=against_count > for_count,
            human_approval_required=True,
        )
