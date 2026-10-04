//! Parimutuel betting pool for AI Agent Arena matches (devnet SOL only).
//!
//! The orchestrator opens a pool with the commit hash of the challenge set,
//! spectators bet on an agent, the orchestrator locks at match start and
//! resolves with the winner + revealed hash, and winners claim pro rata.
use anchor_lang::prelude::*;
use anchor_lang::system_program;

// Replace with the real program ID after `anchor keys sync`.
declare_id!("11111111111111111111111111111111");

pub const MAX_AGENTS: usize = 4;

#[program]
pub mod arena_betting {
    use super::*;

    pub fn create_match(ctx: Context<CreateMatch>, match_id: u64, commit_hash: [u8; 32],
                        num_agents: u8) -> Result<()> {
        require!(num_agents >= 2 && num_agents as usize <= MAX_AGENTS, ArenaError::BadAgentCount);
        let m = &mut ctx.accounts.match_account;
        m.authority = ctx.accounts.authority.key();
        m.match_id = match_id;
        m.commit_hash = commit_hash;
        m.reveal_hash = [0; 32];
        m.num_agents = num_agents;
        m.pools = [0; MAX_AGENTS];
        m.stage = Stage::Open;
        m.winner = u8::MAX;
        m.bump = ctx.bumps.match_account;
        Ok(())
    }

    pub fn place_bet(ctx: Context<PlaceBet>, agent_index: u8, amount: u64) -> Result<()> {
        let m = &mut ctx.accounts.match_account;
        require!(m.stage == Stage::Open, ArenaError::BettingClosed);
        require!(agent_index < m.num_agents, ArenaError::BadAgent);
        require!(amount > 0, ArenaError::ZeroAmount);

        let bet = &mut ctx.accounts.bet;
        if bet.amount == 0 {
            bet.bettor = ctx.accounts.bettor.key();
            bet.match_account = m.key();
            bet.agent_index = agent_index;
            bet.bump = ctx.bumps.bet;
        }
        require!(bet.agent_index == agent_index, ArenaError::OneAgentPerBet);

        system_program::transfer(
            CpiContext::new(ctx.accounts.system_program.to_account_info(),
                            system_program::Transfer {
                                from: ctx.accounts.bettor.to_account_info(),
                                to: m.to_account_info(),
                            }),
            amount,
        )?;
        bet.amount = bet.amount.checked_add(amount).ok_or(ArenaError::Overflow)?;
        m.pools[agent_index as usize] += amount;
        Ok(())
    }

    pub fn lock(ctx: Context<Authority>) -> Result<()> {
        let m = &mut ctx.accounts.match_account;
        require!(m.stage == Stage::Open, ArenaError::WrongStage);
        m.stage = Stage::Locked;
        Ok(())
    }

    pub fn resolve(ctx: Context<Authority>, winner: u8, reveal_hash: [u8; 32]) -> Result<()> {
        let m = &mut ctx.accounts.match_account;
        require!(m.stage == Stage::Locked, ArenaError::WrongStage);
        require!(winner < m.num_agents, ArenaError::BadAgent);
        // The revealed challenge set must hash to what was committed before betting.
        require!(reveal_hash == m.commit_hash, ArenaError::RevealMismatch);
        m.winner = winner;
        m.reveal_hash = reveal_hash;
        m.stage = Stage::Resolved;
        Ok(())
    }

    pub fn claim(ctx: Context<Claim>) -> Result<()> {
        let m = &ctx.accounts.match_account;
        let bet = &mut ctx.accounts.bet;
        require!(m.stage == Stage::Resolved, ArenaError::WrongStage);
        require!(!bet.claimed, ArenaError::AlreadyClaimed);

        let total: u64 = m.pools.iter().sum();
        let winning = m.pools[m.winner as usize];
        let payout = if winning == 0 {
            bet.amount // nobody backed the winner: refund
        } else if bet.agent_index == m.winner {
            ((bet.amount as u128 * total as u128) / winning as u128) as u64
        } else {
            0
        };
        bet.claimed = true;
        require!(payout > 0, ArenaError::NothingToClaim);

        // The match PDA holds the pool; it is program-owned so we move lamports directly.
        **ctx.accounts.match_account.to_account_info().try_borrow_mut_lamports()? -= payout;
        **ctx.accounts.bettor.to_account_info().try_borrow_mut_lamports()? += payout;
        Ok(())
    }
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace)]
pub enum Stage {
    Open,
    Locked,
    Resolved,
}

#[account]
#[derive(InitSpace)]
pub struct MatchAccount {
    pub authority: Pubkey,
    pub match_id: u64,
    pub commit_hash: [u8; 32],
    pub reveal_hash: [u8; 32],
    pub num_agents: u8,
    pub pools: [u64; MAX_AGENTS],
    pub stage: Stage,
    pub winner: u8,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct BetAccount {
    pub bettor: Pubkey,
    pub match_account: Pubkey,
    pub agent_index: u8,
    pub amount: u64,
    pub claimed: bool,
    pub bump: u8,
}

#[derive(Accounts)]
#[instruction(match_id: u64)]
pub struct CreateMatch<'info> {
    #[account(init, payer = authority, space = 8 + MatchAccount::INIT_SPACE,
              seeds = [b"match", match_id.to_le_bytes().as_ref()], bump)]
    pub match_account: Account<'info, MatchAccount>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct PlaceBet<'info> {
    #[account(mut, seeds = [b"match", match_account.match_id.to_le_bytes().as_ref()],
              bump = match_account.bump)]
    pub match_account: Account<'info, MatchAccount>,
    #[account(init_if_needed, payer = bettor, space = 8 + BetAccount::INIT_SPACE,
              seeds = [b"bet", match_account.key().as_ref(), bettor.key().as_ref()], bump)]
    pub bet: Account<'info, BetAccount>,
    #[account(mut)]
    pub bettor: Signer<'info>,
    pub system_program: Program<'info, System>,
}

/// Only the orchestrator keypair that opened the match can lock or resolve it.
#[derive(Accounts)]
pub struct Authority<'info> {
    #[account(mut, has_one = authority)]
    pub match_account: Account<'info, MatchAccount>,
    pub authority: Signer<'info>,
}

#[derive(Accounts)]
pub struct Claim<'info> {
    #[account(mut, seeds = [b"match", match_account.match_id.to_le_bytes().as_ref()],
              bump = match_account.bump)]
    pub match_account: Account<'info, MatchAccount>,
    #[account(mut, has_one = bettor, has_one = match_account,
              seeds = [b"bet", match_account.key().as_ref(), bettor.key().as_ref()], bump = bet.bump)]
    pub bet: Account<'info, BetAccount>,
    #[account(mut)]
    pub bettor: Signer<'info>,
}

#[error_code]
pub enum ArenaError {
    #[msg("A match needs 2 to 4 agents")]
    BadAgentCount,
    #[msg("Betting is closed")]
    BettingClosed,
    #[msg("Unknown agent index")]
    BadAgent,
    #[msg("Amount must be positive")]
    ZeroAmount,
    #[msg("A wallet can only back one agent per match")]
    OneAgentPerBet,
    #[msg("Arithmetic overflow")]
    Overflow,
    #[msg("Match is in the wrong stage")]
    WrongStage,
    #[msg("Revealed hash does not match the commit")]
    RevealMismatch,
    #[msg("Already claimed")]
    AlreadyClaimed,
    #[msg("Nothing to claim")]
    NothingToClaim,
}
