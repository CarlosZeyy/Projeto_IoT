-- 003_tool_object_types: the hand tools of phase 2 and the grade groups of ADR-021 on
-- inspections (SPEC-016 section 4.2, docs/architecture.md section 5).
--
-- * inspections_object_type_check accepts the 8 values of qc_contracts.ObjectType 0.4.0.
-- * inspections_grade_null_iff_unknown gets the check equivalent to the invariant of the
--   contract 0.4.0: grade required for screw and nut, forbidden for unknown, optional for the
--   hand tools. The constraint keeps its name (the one SPEC-003 and the tests already know);
--   only the expression changes.
--
-- Every row valid before stays valid: both new checks only accept more. is_defective (the
-- generated column) does not change.
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
                    'phillips_screwdriver'
                )
            );

    -- Grade-required types (screw, nut) => grade not null; grade-forbidden types (unknown) =>
    -- grade null; the grade-optional types (the hand tools) accept both. For the 8 values that
    -- inspections_object_type_check accepts, this is exactly the expression of SPEC-016
    -- section 4.2: (object_type in ('screw', 'nut') and grade is not null)
    -- or (object_type = 'unknown' and grade is null) or object_type in (<the 5 tools>).
    -- Written as two implications so that a value outside the enum is refused only by
    -- inspections_object_type_check, as before this migration (SQLSTATE 23514 either way).
    alter table inspections
        drop constraint if exists inspections_grade_null_iff_unknown,
        add constraint inspections_grade_null_iff_unknown
            check (
                (object_type not in ('screw', 'nut') or grade is not null)
                and (object_type <> 'unknown' or grade is null)
            );
end
$$;
