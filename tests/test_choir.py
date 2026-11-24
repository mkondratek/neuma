import numpy as np

from neuma import choir

SR = 22050


def tone(hz=220.0, seconds=1.0):
    t = np.arange(int(seconds * SR)) / SR
    return np.sin(2 * np.pi * hz * t)


def test_detunes_are_centred_distinct_and_bounded():
    cents = choir.detunes(4, 8)
    assert len(set(cents)) == 4
    assert abs(sum(cents)) < 1e-9
    assert max(cents) == 8 and min(cents) == -8
    assert choir.detunes(1, 8) == [0.0]
    assert choir.detunes(4, 8, seed=3) == choir.detunes(4, 8, seed=3)


def test_loosen_delays_by_the_offset():
    click = np.zeros(SR)
    click[1000] = 1.0
    late = choir.loosen(click, SR, offset_ms=20, wander_ms=0)
    assert abs(int(np.argmax(late)) - (1000 + round(0.020 * SR))) <= 1


def test_loosen_wanders_within_bounds_and_keeps_length():
    clicks = np.zeros(4 * SR)
    at = np.arange(SR // 10, 4 * SR - SR // 10, SR // 10)
    clicks[at] = 1.0
    late = choir.loosen(clicks, SR, offset_ms=10, wander_ms=5, seed=1)
    assert len(late) == len(clicks)
    delays_ms = [(np.argmax(late[a : a + SR // 20]) / SR) * 1000 for a in at]
    assert 4.9 <= min(delays_ms) and max(delays_ms) <= 15.1
    assert max(delays_ms) - min(delays_ms) > 1  # it does move


def test_impulse_decays_by_60_db_over_the_decay_time():
    impulse = choir.church_impulse(SR, decay_s=2.0, predelay_ms=0)
    assert impulse.shape[1] == 2

    def level(at_s):
        window = impulse[int(at_s * SR) : int((at_s + 0.1) * SR)]
        return 10 * np.log10(np.mean(window**2))

    assert 25 < level(0.1) - level(1.1) < 40  # 30 dB per second for the low band
    assert not np.allclose(impulse[:, 0], impulse[:, 1])  # the two ears differ


def test_reverb_adds_a_tail_and_keeps_the_dry_signal():
    dry = np.stack([tone(seconds=0.5)] * 2, axis=1)
    wet = choir.reverb(dry, SR, decay_s=1.0, wet=0.3)
    assert len(wet) > len(dry) + SR  # rings on for more than a second
    assert np.abs(wet[len(dry) + SR // 10 :]).max() > 0
    assert np.allclose(choir.reverb(dry, SR, decay_s=1.0, wet=0.0)[: len(dry)], dry)


def test_mix_is_stereo_normalised_and_repeatable():
    voices = [tone(220), tone(221), tone(219, seconds=0.9)]
    out = choir.mix(voices, SR, decay_s=1.0)
    assert out.ndim == 2 and out.shape[1] == 2
    assert np.isclose(np.abs(out).max(), 0.7)
    assert not np.allclose(out[:, 0], out[:, 1])
    assert np.array_equal(out, choir.mix(voices, SR, decay_s=1.0))
    assert not np.array_equal(out, choir.mix(voices, SR, decay_s=1.0, seed=1))


def test_mix_without_reverb_keeps_the_length():
    assert len(choir.mix([tone(), tone(222)], SR, wet=0)) == SR


def test_one_voice_is_centred():
    out = choir.mix([tone()], SR, wet=0)
    assert np.allclose(out[:, 0], out[:, 1])


def test_join_overlaps_each_piece_with_the_tail_before_it():
    a = np.stack([tone(seconds=1.0)] * 2, axis=1)
    b = np.stack([tone(330, seconds=0.5)] * 2, axis=1)
    out = choir.join([a, b, a], SR, overlap_s=0.2)
    assert out.shape == (22050 + 11025 + 22050 - 2 * 4410, 2)
    assert np.isclose(np.abs(out).max(), 0.7)


def test_join_never_starts_before_the_beginning():
    short = np.stack([tone(seconds=0.1)] * 2, axis=1)
    assert len(choir.join([short, short], SR, overlap_s=1.0)) == len(short)


def test_warmth_fills_the_low_mids_and_softens_the_top():
    def level(x):
        return 20 * np.log10(np.sqrt(np.mean(x**2)))

    for hz, change in ((250, 3.0), (7000, -4.0 / (1 + 0.5**4)), (1000, 0.4)):
        assert abs(level(choir.warm(tone(hz), SR, 3)) - level(tone(hz)) - change) < 0.3

