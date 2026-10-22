// Prompts ask for measured comparisons, not unsupported tactical explanations.
export type QuestionBank = Record<string, Record<'team' | 'player', Record<string, string[]>>>;

export const expandedQuestions: QuestionBank = {
  cfb: {
    team: {
      results: [
        "How did this team's scoring margin and win rate change, considering the opponents faced in each window?",
        "Did the results change more through points scored or points allowed?",
        "Was the change sustained across games, or concentrated in a few lopsided results?",
        "Which games best support—and challenge—the overall results trend?",
        "How does the regular-season sample compare with the bowl or playoff sample?",
        "How much does the mix of FBS and FCS opponents limit this comparison?",
        "Did conference realignment change the schedule composition enough to complicate the comparison?",
        "How reliable is the results trend given unequal game counts and incomplete coverage?"
      ],
      offense: [
        "Did this team's offensive production change through passing output, rushing efficiency, or third-down conversion?",
        "Did changes in play volume or yards per attempt matter more to offensive production?",
        "Did the passing and rushing games improve together, or did one offset a decline in the other?",
        "How did turnover frequency change alongside offensive production?",
        "Were third- and fourth-down conversion changes supported by enough recorded attempts?",
        "Was the offensive change broad-based across games or driven by a few outliers?",
        "Where modeled EPA is available in both windows, did passing or rushing contribute more to the efficiency change?",
        "Where modeled EPA is available, did EPA-positive play rate move with average EPA per play?",
        "Where modeled pass expectation is available, did pass rate over expected change alongside offensive efficiency?",
        "Which recorded plays illustrate—and contradict—the offensive trend without treating examples as the whole sample?",
        "How do opponent subdivision and schedule composition limit the offensive comparison?"
      ]
    },
    player: {
      quarterback: [
        "Did this quarterback's passing production change through attempt volume, completion rate, or yards per attempt?",
        "How did passing touchdowns and interceptions change relative to attempts and games played?",
        "Was the passing change sustained across games or driven by a few explosive performances?",
        "Did increased passing workload come with better efficiency or diminishing returns?",
        "Which recorded passing plays best represent—and contradict—the overall trend?",
        "Where modeled EPA and CPOE are available, did completion performance and passing efficiency move together?",
        "How reliable is the comparison given verified player attribution and covered passing plays?",
        "If this quarterback transferred, which verified schools and games contribute to each window?"
      ],
      rushing: [
        "Did this runner's production change through workload or yards per carry?",
        "Did increased carry volume come with better efficiency or diminishing returns?",
        "How did rushing touchdowns change relative to carries and covered games?",
        "Was the rushing change consistent across games or driven by a few large performances?",
        "Which recorded carries best illustrate the runner's positive outcomes and counterexamples?",
        "Where modeled EPA is available, did per-carry efficiency agree with yards per carry?",
        "How reliable is the rushing trend given unequal workloads and verified play attribution?",
        "If this runner transferred, what verified school and opponent context differs between windows?"
      ],
      receiving: [
        "Did this receiver's production change through receptions or yards per reception?",
        "How did receiving touchdowns change relative to receptions and covered games?",
        "Was the receiving change sustained across games or driven by a few explosive performances?",
        "Did higher reception volume come with improved or reduced yards per catch?",
        "Which recorded targets best illustrate positive production and missed opportunities?",
        "Where modeled EPA and target attribution are available, did per-target efficiency support the receiving trend?",
        "How reliable is the comparison given covered games and incomplete target attribution?",
        "If this receiver transferred, which verified schools and games are represented in each window?"
      ]
    }
  },
  soccer: {
    team: {
      results: [
        "Did this team's change in points per match come mainly from more wins, fewer losses, or a different draw rate?",
        "Did goals scored and goals conceded support the change in results?",
        "Were better results sustained across matches or driven by a few high-scoring wins?",
        "Which matches best support—and challenge—the results trend?",
        "Where xG is recorded, did expected goal difference move with points per match?",
        "How reliable is the results comparison given unequal match counts and source coverage?"
      ],
      attack: [
        "Did this team's shot volume and shots on target move together across the two windows?",
        "Did scoring improve without a corresponding rise in recorded shooting output?",
        "Where xG is recorded, did non-penalty xG and total xG tell the same attacking story?",
        "Where goals and xG cover the same matches, was the scoring change supported by xG or finishing above expectation?",
        "Was attacking production sustained across matches or concentrated in a few outliers?",
        "Which matches best illustrate the attacking trend, and what coverage gaps limit the conclusion?"
      ],
      defense: [
        "Was the change in goals conceded broad-based or dominated by a few heavy defeats?",
        "Where xG against is recorded, did goals conceded improve alongside the expected chances allowed?",
        "Do defensive results look different when restricted to matches with comparable xG coverage?",
        "Which matches best support—and contradict—the defensive trend?",
        "How much uncertainty comes from match count and missing defensive statistics?"
      ],
      control: [
        "Did higher recorded possession coincide with more shots and shots on target?",
        "Did possession change without a corresponding improvement in results?",
        "Was the possession trend consistent across covered matches?",
        "Which matches show that possession alone does not explain the results?",
        "For full-season windows, where published passing totals are available, do they support the possession comparison without implying a tactical cause?"
      ]
    },
    player: {
      usage: [
        "Did this player's appearances and starts increase together?",
        "Did the share of recorded appearances that were starts change?",
        "How much of the appearance difference reflects unequal numbers of team matches?",
        "Was the change in starts sustained across the covered matches?",
        "For full-season windows, where published minutes are recorded, did minutes and appearances tell the same usage story?",
        "How do incomplete lineup records limit the usage comparison?"
      ],
      scoring: [
        "Did this player's goals change alongside appearances, or did production per recorded appearance change?",
        "Were goals spread across matches or concentrated in a few large performances?",
        "Where recorded, how did assists change alongside goals?",
        "Where player xG is recorded, did non-penalty expected goals support the scoring trend?",
        "Where goals and xG share coverage, did finishing above expectation account for much of the difference?",
        "Which recorded matches and scoring events best support—and challenge—the production trend?",
        "How reliable is the scoring comparison given appearance counts and missing player xG?"
      ],
      discipline: [
        "Did this player's card count change faster than recorded appearances?",
        "Were cards spread across matches or concentrated in a few incidents?",
        "Which recorded card events explain the discipline comparison?",
        "How do unequal appearance counts and incomplete event coverage affect the conclusion?",
        "Does the evidence support a discipline trend, or is the sample too small?"
      ]
    }
  },
  nba: {
    team: {
      offense: ["Did offensive rating improve even when points per game did not, after considering pace?", "Did free-throw production reinforce or offset the change in shooting efficiency?"],
      defense: ["Did defensive rating and net rating move in the same direction?", "Which representative possessions illustrate defensive outcomes without inferring unrecorded coverage assignments?"],
      shooting: ["Did free-throw production explain a gap between effective field-goal and true shooting trends?", "Where shot locations are recorded, did the rim and three-point attempt mix change alongside efficiency?"],
      playmaking: ["Did assists rise faster than turnovers as possession volume changed?", "Where recorded possession evidence is available, which sequences illustrate the assist-to-turnover trend?"],
      rebounding: ["Did offensive and defensive rebounding move in different directions?", "Does the evidence show more rebounds, or a better share of available rebounds where that denominator is recorded?"],
      turnovers: ["Did turnover rate improve even if turnovers per game increased with pace?", "Which recorded turnover possessions best represent typical mistakes rather than just the worst game?"],
      lineups: ["Did returning five-player units improve, or did the team shift minutes toward different combinations?", "How much does the lineup conclusion depend on the minimum possession sample?"]
    },
    player: {
      scoring: ["Did this player's scoring rise because of minutes, usage, or scoring efficiency?", "Did free-throw production support scoring when field-goal efficiency fell?"],
      shooting: ["Did this player's effective field-goal and true shooting percentages tell different stories because of free throws?", "Where shot locations are recorded, did this player's shot mix change or mainly the conversion rate?"],
      playmaking: ["Did this player's assist-to-turnover results hold as usage increased?", "Were playmaking gains sustained across games with different minutes totals?"],
      rebounding: ["Did this player's offensive and defensive rebounding change in different directions?", "Were rebounding gains explained mainly by more minutes rather than stronger per-minute production?"],
      turnovers: ["Did this player's ball security improve as playmaking responsibility increased?", "How sensitive is the turnover comparison to a few high-turnover games?"],
      usage: ["Did this player's minutes and usage move in opposite directions?", "Did efficiency hold when this player took on a larger offensive workload?"],
      impact: ["Do this player's box-score improvements agree with the recorded plus/minus trend?", "How much uncertainty remains before attributing lineup results to this player individually?"],
      lineups: ["Did this player's returning units improve, or did different combinations receive more minutes?", "Do the strongest units remain convincing when low-possession combinations are excluded?"]
    }
  }
};
