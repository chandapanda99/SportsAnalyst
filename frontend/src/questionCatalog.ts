import type {QuestionBank} from './expandedQuestions';
export const questionBanks: QuestionBank = {
  nfl: {
    team: {
      passing: [
        "What drove the change in this offense's EPA per dropback: down-to-down success, completion performance, or explosive passes?",
        "Did the passing game become consistently more efficient, or did a handful of explosive plays and outlier games drive the difference?",
        "How did the offense's passing profile change in accuracy, success rate, and explosive-pass frequency?",
        "When did the passing-efficiency trend meaningfully shift, and was that change sustained across the comparison window?",
        "Which representative dropbacks best explain—and challenge—the overall passing-efficiency trend?"
      ],
      rushing: [
        "What drove the change in this rushing attack's EPA per carry: success rate, yards per carry, or explosive-run frequency?",
        "Did the run game improve by staying on schedule more often, or by generating more explosive gains?",
        "Was the rushing change sustained across the full window, or concentrated in a few games?",
        "How did the rushing attack's efficiency and consistency change from the baseline to the comparison period?",
        "Which carries best illustrate the run game's positive and negative outcomes?"
      ],
      offense: [
        "What drove the change in overall offensive EPA per play: efficiency, yards per play, or turnover rate?",
        "Did the offense become better at sustaining successful plays, or was the difference mostly created by high-leverage gains?",
        "How much of the offensive change came from play mix versus performance within the passing and rushing games?",
        "Was the offense's improvement or decline broad-based across the window, or concentrated in a few games?",
        "Which plays provide the clearest evidence for—and against—the overall offensive trend?"
      ]
    },
    player: {
      quarterback: [
        "What drove the change in this quarterback's EPA per dropback: success rate, CPOE, or yards per dropback?",
        "Did this quarterback become more consistently efficient, or did a few high-variance games drive the result?",
        "How did this quarterback's accuracy relative to expectation translate into changes in overall passing efficiency?",
        "When did this quarterback's performance trend shift, and was the change sustained?",
        "Which dropbacks best represent—and contradict—this quarterback's overall performance trend?"
      ],
      receiving: [
        "Did this receiver's production change because of target volume, catch rate, yards per target, or EPA per target?",
        "How did this receiver's role and per-target efficiency change between the two windows?",
        "Was this receiver's change sustained across the sample, or driven by a few high-volume or explosive games?",
        "Did the receiver convert opportunities more efficiently even if target volume changed?",
        "Which targets best illustrate the receiver's positive production and missed opportunities?"
      ],
      running: [
        "Did this ball carrier's production change because of workload, EPA per carry, success rate, or yards per carry?",
        "How did this runner's down-to-down efficiency change relative to the volume of carries received?",
        "Was the rushing change consistent across games, or driven by a few large performances?",
        "Did increased workload come with better efficiency, diminishing returns, or no meaningful change?",
        "Which carries best represent the runner's efficiency trend and its counterexamples?"
      ]
    }
  },
  soccer: {
    team: {
      results: ['Did this team improve its points per match, and was the change driven by scoring or defending?'],
      attack: ['Did this team create more shots and shots on target as its goals per match changed?',
        'Where expected goals are recorded, did attacking output change through chance quality or goals scored above xG?'],
      defense: ['Did the team concede fewer goals consistently across the selected matches?',
        'Where xG against is recorded, did the team allow fewer or lower-quality chances?'],
      control: ['Did possession change alongside the team’s results and attacking output?']
    },
    player: {
      usage: ['Did this player feature and start more often across these periods?'],
      scoring: ['Did this player score more often across the selected matches?',
        'Where player xG is recorded, how did expected goals and goals above xG change across the covered appearances?'],
      discipline: ['Did this player receive more cards across these periods?']
    }
  },
  nba: {
    team: {
      offense: [
        "What drove the change in this team's offensive rating: scoring volume, effective field-goal percentage, or turnover control?",
        "Did the offense improve through better shot-making, cleaner possessions, or both?",
        "Was the offensive change sustained across the season, or concentrated in a small number of games?",
        "How did the team's scoring efficiency translate into changes in win percentage?",
        "Which games best represent—and challenge—the overall offensive trend?"
      ],
      defense: [
        "How did this team's defensive rating change, and how closely did that track with its win percentage?",
        "Was the defensive improvement or decline sustained across the season, or driven by a few outlier games?",
        "When did the team's defensive-efficiency trend meaningfully change?",
        "Did the defense become more consistent from game to game, even if its average rating changed only modestly?",
        "Which games provide the strongest evidence for—and against—the defensive trend?"
      ],
      shooting: [
        "Was the change in team shooting efficiency driven by shot-making, three-point attempt rate, or both?",
        "How did effective field-goal percentage and true shooting percentage move relative to the team's three-point mix?",
        "Did the team generate a more efficient shot profile, or simply convert similar shots at a better rate?",
        "Was the shooting change stable across the window or concentrated in hot and cold stretches?",
        "Which games best illustrate the team's changing shooting profile?"
      ],
      playmaking: [
        "Did the team's ball movement improve, based on assists per game and assist-to-turnover ratio?",
        "Was the change in playmaking driven by creating more assisted baskets or by protecting possessions more effectively?",
        "How consistently did the team generate assists without increasing turnovers?",
        "When did the team's assist-to-turnover profile begin to change?",
        "Which games best represent the team's strongest and weakest playmaking performances?"
      ],
      rebounding: [
        "Did this team improve on the glass through total rebounding, offensive rebounding, or both?",
        "How much did second-chance opportunity creation change between the two windows?",
        "Was the rebounding change consistent across games or driven by a few dominant performances?",
        "When did the team's rebounding trend shift during the season?",
        "Which games best illustrate the team's rebounding strengths and weaknesses?"
      ],
      turnovers: [
        "Did this team protect the ball more effectively, based on turnovers per game and turnover rate?",
        "Was the change in turnovers proportional to the team's possession volume, or did its underlying ball security change?",
        "How consistent was the team's turnover control across the comparison window?",
        "When did the team's turnover profile begin to improve or deteriorate?",
        "Which games had the greatest influence on the team's turnover trend?"
      ],
      lineups: [
        "Which five-player units drove the change in net rating between these windows?",
        "Did the team's best lineups improve through offense, defense, or both?",
        "How concentrated was the team's performance among its most-used lineup combinations?",
        "Which lineup changes produced the clearest gains or losses in efficiency?",
        "Did the strongest lineup results persist across the full window or come from limited samples?"
      ]
    },
    player: {
      scoring: [
        "Did this player's scoring change because of volume, true shooting efficiency, or both?",
        "How efficiently did this player convert a changing scoring workload?",
        "Was the scoring change sustained across games or driven by a few high-output performances?",
        "When did this player's scoring trend meaningfully shift?",
        "Which games best represent—and challenge—the player's overall scoring trend?"
      ],
      shooting: [
        "Did this player's shooting efficiency change because of shot-making, three-point attempt rate, or both?",
        "How did effective field-goal percentage and true shooting percentage move as the player's shot mix changed?",
        "Did the player become a more efficient shooter, or simply take a different distribution of shots?",
        "Was the shooting change sustained, or concentrated in hot and cold stretches?",
        "Which games best illustrate the player's changing shooting profile?"
      ],
      playmaking: [
        "Did this player's creation improve through more assists, better assist-to-turnover efficiency, or both?",
        "How did this player's role as a primary or secondary creator change between the two windows?",
        "Was the playmaking change consistent across games or driven by a few high-assist performances?",
        "Did additional ball-handling responsibility produce better distribution without a comparable rise in turnovers?",
        "Which games best represent the player's strongest and weakest playmaking performances?"
      ],
      rebounding: [
        "Did this player's rebounding change through total activity, offensive-board production, or both?",
        "How did this player's impact on second-chance opportunities change between the two windows?",
        "Was the rebounding change sustained or driven by a few matchup-specific performances?",
        "When did this player's rebounding trend begin to shift?",
        "Which games best illustrate the player's work on the glass?"
      ],
      turnovers: [
        "How did this player's turnover volume change between the two windows?",
        "Was the change in ball security sustained across games or driven by a few high-turnover performances?",
        "When did this player's turnover trend begin to improve or deteriorate?",
        "Did the player's turnover burden change alongside a larger offensive role?",
        "Which games had the greatest influence on the player's turnover trend?"
      ],
      usage: [
        "How did this player's offensive role change in minutes and usage proxy between the two windows?",
        "Did a larger role come from more playing time, more involvement per minute, or both?",
        "Was the player's increased usage sustained across the sample or concentrated in specific stretches?",
        "When did this player's rotation role and offensive involvement begin to change?",
        "Did the player's workload expand without a comparable change in minutes?"
      ],
      impact: [
        "How did this player's plus/minus impact change, and what does the lineup context suggest about that shift?",
        "Was the player's impact trend sustained across the window or driven by a few extreme games?",
        "Did the lineups featuring this player improve even when individual box-score production was stable?",
        "When did this player's impact trend meaningfully change?",
        "Which games and lineup contexts best explain the player's change in impact?"
      ],
      lineups: [
        "Which five-player units best complemented this player between the two windows?",
        "Did this player's most-used lineups improve through offense, defense, or both?",
        "How dependent was the player's lineup impact on a small number of teammates or units?",
        "Which lineup combinations produced the clearest gains or losses with this player on the floor?",
        "Were the player's strongest lineup results supported by meaningful samples or limited minutes?"
      ]
    }
  }
};
export const supplementalQuestionBanks: QuestionBank = {
  nfl: {
    team: {
      passing: [
        "How much did sacks, turnovers, and pressure-sensitive outcomes influence the passing-efficiency change?",
        "Did the passing offense improve across downs and game situations, or only in a narrow set of favorable contexts?",
        "How did opponent quality and game-to-game volatility affect the apparent passing trend?"
      ],
      rushing: [
        "Did rushing efficiency change across downs, distances, and field position, or only in favorable situations?",
        "How much did opponent quality and game script shape the rushing comparison?",
        "Were changes in negative runs and explosive gains more important than the average yards-per-carry result?"
      ],
      offense: [
        "Which phase—passing, rushing, sacks, or turnovers—accounted for the largest share of the offensive change?",
        "Did the offense improve across score states and field zones, or mostly when game conditions were favorable?",
        "How robust is the offensive trend after accounting for opponent strength and outlier games?"
      ]
    },
    player: {
      quarterback: [
        "How much did sacks, interceptions, and explosive completions shape this quarterback's efficiency change?",
        "Did this quarterback improve across the full game sample, or mainly against particular opponents?",
        "How reliable is the comparison given the number and distribution of recorded dropbacks?"
      ],
      receiving: [
        "Did changes in target opportunity or per-target results matter more to this receiver's production?",
        "How much of this receiver's change came from explosive catches versus repeatable down-to-down efficiency?",
        "How reliable is the receiving trend across games and recorded targets?"
      ],
      running: [
        "Did changes in carry volume or per-carry efficiency matter more to this runner's production?",
        "How much of this runner's change came from explosive carries versus avoiding negative outcomes?",
        "How reliable is the rushing trend across games and recorded attempts?"
      ]
    }
  },
  nba: {
    team: {
      offense: [
        "How much did pace, shooting efficiency, and turnover rate each contribute to the offensive change?",
        "Did the offense perform differently by opponent, venue, rest, or game state?",
        "How robust is the offensive-rating trend after reducing the influence of outlier games?"
      ],
      defense: [
        "Did opponent quality, venue, or rest explain part of the defensive-rating change?",
        "Was the defensive change driven by repeatable possession outcomes or unusually hot and cold opponent shooting?",
        "Which periods and score states contributed most to the defensive trend?"
      ],
      shooting: [
        "How did rim, midrange, and three-point outcomes contribute to the change where shot detail is available?",
        "Did shooting efficiency hold across opponents and venues, or depend on a few favorable matchups?",
        "How much uncertainty comes from three-point variance and the number of recorded attempts?"
      ],
      playmaking: [
        "Did playmaking results change with pace, opponent pressure, or game state?",
        "Were assist gains distributed across the roster or concentrated among a few creators?",
        "How much of the assist-to-turnover change remained after excluding outlier games?"
      ],
      rebounding: [
        "Did rebounding performance vary materially by opponent size, venue, or rest?",
        "Were extra possessions created consistently or concentrated in a few matchup advantages?",
        "How closely did changes on the glass translate into scoring and net-rating results?"
      ],
      turnovers: [
        "Which opponents, periods, and score states produced the largest changes in turnover rate?",
        "Did ball security improve independently of pace and possession volume?",
        "Were live-ball mistakes or a handful of extreme games disproportionately influential where event detail is available?"
      ],
      lineups: [
        "Which high-minute units provide the strongest evidence after accounting for lineup sample size?",
        "Which new, departed, and returning combinations explain the change between periods?",
        "Were lineup results stable across opponents, or driven by a small set of favorable matchups?"
      ]
    },
    player: {
      scoring: [
        "Did opponent, venue, rest, or game state materially change this player's scoring comparison?",
        "How much of the scoring change came from shot volume, free throws, and shooting efficiency?",
        "How robust is the scoring trend after accounting for minutes and outlier games?"
      ],
      shooting: [
        "How did this player's efficiency vary by shot value and distance where shot detail is available?",
        "Did opponent, venue, or rest meaningfully affect this player's shooting results?",
        "How much uncertainty comes from attempt volume and three-point variance?"
      ],
      playmaking: [
        "Did this player's creation change with lineup partners, opponent, or game state?",
        "How did assists and turnovers change relative to minutes and offensive involvement?",
        "Was the playmaking trend broad-based or concentrated in a few high-creation games?"
      ],
      rebounding: [
        "Did this player's rebounding change with minutes, lineup role, or opponent matchup?",
        "How consistently did this player create offensive-board opportunities across games?",
        "Did the rebounding change translate into stronger lineup or team outcomes?"
      ],
      turnovers: [
        "How did this player's turnovers change relative to minutes, usage, and playmaking responsibility?",
        "Did particular opponents or game states account for a disproportionate share of the turnovers?",
        "Was the ball-security trend stable after excluding extreme games?"
      ],
      usage: [
        "Did this player's efficiency rise, hold, or decline as offensive involvement changed?",
        "How did lineup partners and team stint affect this player's role?",
        "Was the usage change consistent across games, opponents, and rest situations?"
      ],
      impact: [
        "How much of this player's impact change can be separated from lineup and opponent context?",
        "Did offense, defense, or a small number of high-leverage games drive the plus/minus trend?",
        "Which high-minute lineup contexts support or contradict the individual impact result?"
      ],
      lineups: [
        "Which high-minute units with this player remain strongest after considering sample size?",
        "Which teammate combinations changed most between the two periods?",
        "Did this player's lineup results persist across opponents and game situations?"
      ]
    }
  }
};
