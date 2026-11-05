-- 007_identified_tool_object_types: hammer, wrench and spirit level on inspections, the
-- identification-only tools of ADR-025 (SPEC-044 section 4.2, ADR-021, docs/architecture.md
-- section 5).
--
-- * inspections_object_type_check accepts the 15 values of qc_contracts.ObjectType 0.7.0.
-- * inspections_grade_null_iff_unknown gets the check equivalent to the invariant of the
--   contract 0.7.0: grade required for screw and nut; forbidden for unknown, the 4 power tools
--   and the 3 identification-only tools (hammer, wrench, spirit_level); optional for the hand
--   tools. The constraint keeps its name (the one SPEC-003, SPEC-016, SPEC-021 and the tests
--   already know); only the expression changes.
--
-- Every row valid before stays valid: no row can hold one of the 3 new values yet, and for the
-- 12 older values both checks give the same result as in 006. is_defective (the generated
-- column) does not change.
--
-- No BEGIN/COMMIT here: the transaction belongs to infra/migrate.py. One single DO block, so
-- the drops and the adds succeed or fail together, also in a psql session without
-- ON_ERROR_STOP. Idempotent: running this file again (SQL Editor / psql / runner) replaces each
-- check by the same expression, without error. No credentials here (R-03).

do $$
begin
    alter table inspections
        drop constraint if exists inspections_object_type_check,
        add constraint inspections_object_type_check
            check (
                object_type in (
                    'screw',
                    'nut',
                    'unknown',
                    'pliers',
                    'adjustable_wrench',
                    'allen_key',
                    'flat_screwdriver',
                    'phillips_screwdriver',
                    'angle_grinder',
                    'saw',
                    'drill',
                    'cordless_screwdriver',
                    'hammer',
                    'wrench',
                    'spirit_level'
                )
            );

    -- Grade-required types (screw, nut) => grade not null; grade-forbidden types (unknown, the
    -- power tools and the identification-only tools) => grade null; the grade-optional types
    -- (the hand tools) accept both. For the 15 values that inspections_object_type_check
    -- accepts, this is exactly
    -- (object_type in ('screw', 'nut') and grade is not null)
    -- or (object_type in ('unknown', <the 4 power tools>, <the 3 identified tools>)
    --     and grade is null)
    -- or object_type in (<the 5 hand tools>).
    -- Written as two implications, as in 003 and 006, so that a value outside the enum is
    -- refused only by inspections_object_type_check (SQLSTATE 23514 either way).
    alter table inspections
        drop constraint if exists inspections_grade_null_iff_unknown,
        add constraint inspections_grade_null_iff_unknown
            check (
                (object_type not in ('screw', 'nut') or grade is not null)
                and (
                    object_type not in (
                        'unknown',
                        'angle_grinder',
                        'saw',
                        'drill',
                        'cordless_screwdriver',
                        'hammer',
                        'wrench',
                        'spirit_level'
                    )
                    or grade is null
                )
            );
end
$$;
