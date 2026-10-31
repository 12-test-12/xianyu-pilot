import test from 'node:test'
import assert from 'node:assert/strict'
import { isPublishAddressComplete, normalizePublishAddress } from '../src/utils/publishAddress.js'
import { buildPublishIntentSummary, canSubmitPublishIntent, recoverPublishIntent } from '../src/utils/productPublishState.js'

const region = { prov: '北京市', city: '北京市', area: '东城区', divisionId: '110101', gps: '116.418757,39.917544', poiName: '东城区', poiId: '' }

test('a dictionary region works without inventing a venue POI ID', () => {
  assert.equal(isPublishAddressComplete(region), true)
  assert.equal(normalizePublishAddress(region).poiId, '')
  assert.equal(isPublishAddressComplete({ poiName: '历史地址' }), false)
  assert.equal(isPublishAddressComplete({ ...region, divisionId: '台北市' }), false)
  for (const gps of ['181,30', '116,91', 'NaN,30', ',30', '116,', '116,30,1']) {
    assert.equal(isPublishAddressComplete({ ...region, gps }), false, gps)
  }
})

test('online, unsupported and ambiguous intents keep their original identity and retry restrictions', () => {
  for (const shippingMode of ['none', 'fixed', 'free']) {
    for (const status of ['unknown', 'remote_confirmed', 'failed']) {
      const saved = { idempotencyKey: 'original-key', payload: { shippingMode, freeShipping: false, location: region }, outcome: { status, retrySafe: false } }
      assert.deepEqual(recoverPublishIntent(saved), saved)
      assert.equal(canSubmitPublishIntent({ accountsAvailable: true, hasIntent: true, outcome: saved.outcome }), status === 'remote_confirmed')
    }
  }
  const recovered = recoverPublishIntent({ idempotencyKey: 'original-key', payload: { shippingMode: 'none' } })
  assert.equal(recovered.outcome.status, 'unknown')
  assert.equal(recovered.outcome.retrySafe, false)
})

test('publish confirmation includes the actual delivery mode and region', () => {
  const summary = buildPublishIntentSummary({ shippingMode: 'none', location: region })
  assert.match(summary, /线上交付 \/ 无需邮寄/)
  assert.match(summary, /发布地区：北京市 北京市 东城区/)
})
