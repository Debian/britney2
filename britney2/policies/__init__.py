from enum import Enum, unique

@unique
class PolicyVerdict(Enum):
    """"""
    """
    The policy doesn't apply to this item. No test was done.
    """
    NOT_APPLICABLE = 0
    """
    The migration item passed the policy.
    """
    PASS = 1
    """
    The policy was completely overruled by a hint.
    """
    PASS_HINTED = 2
    """
    The migration item did not pass the policy, but the failure is believed
    to be temporary
    """
    REJECTED_TEMPORARILY = 3
    """
    The migration item is temporarily unable to migrate due to another item.  The other item is temporarily blocked.
    """
    REJECTED_WAITING_FOR_ANOTHER_ITEM = 4
    """
    The migration item is permanently unable to migrate due to another item.  The other item is permanently blocked.
    """
    REJECTED_BLOCKED_BY_ANOTHER_ITEM = 5
    """
    The migration item needs approval to migrate
    """
    REJECTED_NEEDS_APPROVAL = 6
    """
    The migration item is blocked, but there is not enough information to determine
    if this issue is permanent or temporary
    """
    REJECTED_CANNOT_DETERMINE_IF_PERMANENT = 7
    """
    The migration item did not pass the policy and the failure is believed
    to be uncorrectable (i.e. a hint or a new version is needed)
    """
    REJECTED_PERMANENTLY = 8

    @property
    def is_rejected(self):
        return True if self.name.startswith('REJECTED') else False

    @property
    def is_blocked(self):
        """Whether the item (probably) needs a fix or manual assistance to migrate"""
        return self in {
            PolicyVerdict.REJECTED_BLOCKED_BY_ANOTHER_ITEM,
            PolicyVerdict.REJECTED_NEEDS_APPROVAL,
            PolicyVerdict.REJECTED_CANNOT_DETERMINE_IF_PERMANENT, # Assuming the worst
            PolicyVerdict.REJECTED_PERMANENTLY,
        }
